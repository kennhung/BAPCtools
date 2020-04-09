import hashlib
import shlex
import shutil
import yaml as yamllib

from util import *
from pathlib import Path
import build
import validate
import run


# Run generators according to the gen.yaml file.
def generate(problem, settings):
    gen_config, generator_runs = _parse_gen_yaml(problem)

    generate_ans = settings.validation != 'custom interactive'
    submission = None
    retries = 1
    if gen_config:
        if 'generate_ans' in gen_config:
            generate_ans = gen_config['generate_ans']
        if generate_ans and 'submission' in gen_config and gen_config['submission']:
            submission = problem / gen_config['submission']
        if 'retries' in gen_config:
            retries = max(gen_config['retries'], 1)

    if generate_ans and submission is None:
        # Use one of the accepted submissions.
        submissions = list(glob(problem, 'submissions/accepted/*'))
        if len(submissions) == 0:
            warn('No submissions found!')
        else:
            submissions.sort()
            # Look for a c++ solution if available.
            for s in submissions:
                if s.suffix == '.cpp':
                    submission = s
                    break
                else:
                    if submission is None:
                        submission = s
        if submission is not None:
            log(f'No submission was specified in generators/gen.yaml. Falling back to {submission}.'
                )

    if generate_ans and submission is not None:
        if not (submission.is_file() or submission.is_dir()):
            error(f'Submission not found: {submission}')
            submission = None
        else:
            bar = ProgressBar('Building', items=[print_name(submission)])
            bar.start(print_name(submission))
            submission, msg = build.build(submission)
            bar.done(submission is not None, msg)
    if submission is None: generate_ans = False

    input_validators = validate.get_validators(problem, 'input') if len(generator_runs) > 0 else []
    output_validators = validate.get_validators(problem, 'output') if generate_ans else []

    if len(generator_runs) == 0 and generate_ans is False:
        return True

    nskip = 0
    nfail = 0

    timeout = get_timeout()

    # Move source to target but check that --force was passed if target already exists and source is
    # different. Overwriting samples needs --samples as well.
    def maybe_move(source, target, tries_msg=''):
        nonlocal nskip

        # Validate new .in and .ans files
        if source.suffix == '.in':
            if not validate.validate_testcase(problem, source, input_validators, 'input', bar=bar):
                return False
        if source.suffix == '.ans' and settings.validation != 'custom interactive':
            if not validate.validate_testcase(
                    problem, source, output_validators, 'output', bar=bar):
                return False

        # Ask -f or -f --samples before overwriting files.
        if target.is_file():
            if source.read_text() == target.read_text():
                return True

            if 'sample' in str(target) and (not (hasattr(settings, 'samples') and settings.samples)
                                            or
                                            not (hasattr(settings, 'force') and settings.force)):
                bar.warn('SKIPPED: ' + target.name + cc.reset +
                         '; supply -f --samples to overwrite')
                return False

            if not (hasattr(settings, 'force') and settings.force):
                nskip += 1
                bar.warn('SKIPPED: ' + target.name + cc.reset + '; supply -f to overwrite')
                return False

        if target.is_file():
            bar.log('CHANGED: ' + target.name + tries_msg)
        else:
            bar.log('NEW: ' + target.name + tries_msg)
        shutil.move(source, target)
        return False

    tmpdir = config.tmpdir / problem.name / 'generate'
    tmpdir.mkdir(parents=True, exist_ok=True)

    # Generate Input
    if len(generator_runs) > 0:
        bar = ProgressBar('Generate', items=generator_runs)

        for file_name in generator_runs:
            commands = generator_runs[file_name]

            bar.start(str(file_name))

            (problem / 'data' / file_name.parent).mkdir(parents=True, exist_ok=True)

            stdin_path = tmpdir / file_name.name
            stdout_path = tmpdir / (file_name.name + '.stdout')

            # Try running all commands |retries| times.
            ok = True
            for retry in range(retries):
                # Clean the directory.
                for f in tmpdir.iterdir():
                    f.unlink()

                for command in commands:
                    input_command = shlex.split(command)

                    generator_name = input_command[0]
                    input_args = input_command[1:]

                    for i in range(len(input_args)):
                        x = input_args[i]
                        if x == '$SEED':
                            val = int(hashlib.sha512(command.encode('utf-8')).hexdigest(),
                                      16) % (2**31)
                            input_args[i] = (val + retry) % (2**31)

                    generator_command, msg = build.build(problem / 'generators' / generator_name)
                    if generator_command is None:
                        bar.error(msg)
                        ok = False
                        break

                    command = generator_command + input_args

                    stdout_file = stdout_path.open('w')
                    stdin_file = stdin_path.open('r') if stdin_path.is_file() else None
                    try_ok, err, out = exec_command(command,
                                                    stdout=stdout_file,
                                                    stdin=stdin_file,
                                                    timeout=timeout,
                                                    cwd=tmpdir)
                    stdout_file.close()
                    if stdin_file: stdin_file.close()

                    if stdout_path.is_file():
                        shutil.move(stdout_path, stdin_path)

                    if try_ok == -9:
                        # Timeout
                        bar.error(f'TIMEOUT after {timeout}s')
                        nfail += 1
                        ok = False
                        break

                    if try_ok is not True:
                        nfail += 1
                        try_ok = False
                        break

                if not ok: break
                if try_ok: break

            if not try_ok:
                bar.error('FAILED: ' + err)
                ok = False

            tries_msg = '' if retry == 0 else f' after {retry+1} tries'

            # Copy all generated files back to the data directory.
            if ok:
                for f in tmpdir.iterdir():
                    if f.stat().st_size == 0: continue

                    target = problem / 'data' / file_name.parent / f.name
                    ok &= maybe_move(f, target, tries_msg)

            bar.done(ok)

        if not config.verbose and nskip == 0 and nfail == 0:
            print(ProgressBar.action('Generate', f'{cc.green}Done{cc.reset}'))

    if generate_ans is False or submission is None:
        return nskip == 0 and nfail == 0

    # Generate Answer
    _, timeout = get_time_limits(settings)

    if settings.validation != 'custom interactive':
        testcases = get_testcases(problem, needans=False)
        bar = ProgressBar('Generate ans',
                          items=[print_name(t.with_suffix('.ans')) for t in testcases])

        for testcase in testcases:
            bar.start(print_name(testcase.with_suffix('.ans')))

            outfile = tmpdir / testcase.with_suffix('.ans').name
            try:
                outfile.unlink()
            except OSError:
                pass

            # Ignore stdout and stderr from the program.
            ok, duration, err, out = run.run_testcase(submission, testcase, outfile, timeout)
            if ok is not True or duration > timeout:
                if duration > timeout:
                    bar.error('TIMEOUT')
                    nfail += 1
                else:
                    bar.error('FAILED')
                    nfail += 1
            else:
                ensure_symlink(outfile.with_suffix('.in'), testcase)
                ok &= maybe_move(outfile, testcase.with_suffix('.ans'))

            bar.done(ok)

        if not config.verbose and nskip == 0 and nfail == 0:
            print(ProgressBar.action('Generate ans', f'{cc.green}Done{cc.reset}'))

    else:
        # For interactive problems:
        # - create empty .ans files
        # - create .interaction files for samples only
        testcases = get_testcases(problem, needans=False, only_sample=True)
        bar = ProgressBar('Generate interaction',
                          items=[print_name(t.with_suffix('.interaction')) for t in testcases])

        for testcase in testcases:
            bar.start(print_name(testcase.with_suffix('.interaction')))

            outfile = tmpdir / testcase.with_suffix('.interaction').name
            try:
                outfile.unlink()
            except OSError:
                pass

            # Ignore stdout and stderr from the program.
            verdict, duration, err, out = run.process_interactive_testcase(submission,
                                                                           testcase,
                                                                           settings,
                                                                           output_validators,
                                                                           validator_error=None,
                                                                           team_error=None,
                                                                           interaction=outfile)
            if verdict != 'ACCEPTED':
                if duration > timeout:
                    bar.error('TIMEOUT')
                    nfail += 1
                else:
                    bar.error('FAILED')
                    nfail += 1
            else:
                ok &= maybe_move(outfile, testcase.with_suffix('.interaction'))

            bar.done(ok)

        if not config.verbose and nskip == 0 and nfail == 0:
            print(ProgressBar.action('Generate ans', f'{cc.green}Done{cc.reset}'))

    return nskip == 0 and nfail == 0


# Remove all files mentioned in the gen.yaml file.
def clean(problem):
    gen_config, generator_runs = _parse_gen_yaml(problem)
    for file_path in generator_runs:
        f = problem / 'data' / file_path
        if f.is_file():
            print(ProgressBar.action('REMOVE', str(f)))
            f.unlink()

        ansfile = f.with_suffix('.ans')

        if ansfile.is_file():
            print(ProgressBar.action('REMOVE', str(ansfile)))
            ansfile.unlink()

        try:
            f.parent.rmdir()
        except:
            pass

    return True


## NEW


def is_testcase(yaml):
    return yaml == '' or isinstance(yaml, str) or (isinstance(yaml, dict) and 'input' in yaml)


def is_directory(yaml):
    return isinstance(yaml, dict) and 'type' in yaml and yaml['type'] == 'directory'


# Holds all inheritable configuration options. Currently:
# - config.solution
# - config.visualizer
# - config.random_salt
class Config:
    INHERITABLE_KEYS = [
        ('solution', None),
        ('visualizer', None),
        ('random_salt', ''),
    ]

    def __init__(self, yaml=None, parent_config=None):
        assert not yaml or isinstance(yaml, dict)
        for key, default in self.INHERITABLE_KEYS:
            if yaml and key in yaml:
                setattr(self, key, yaml[key])
            elif parent_config is not None:
                setattr(self, key, vars(parent_config)[key])
            else:
                setattr(self, key, default)


class Base:
    def __init__(self, name, yaml, parent):
        assert parent is not None

        if isinstance(yaml, dict):
            self.config = Config(yaml, parent.config)
        else:
            self.config = parent.config

        self.name = name
        self.path: Path = parent.path / self.name


class Testcase(Base):
    def __init__(self, name: str, yaml, parent):
        assert is_testcase(yaml)

        self.manual = False

        if yaml == '':
            self.manual = True
            yaml = {'input': None}
        if isinstance(yaml, str) and yaml.endswith('.in'):
            self.manual = True
            assert not yaml.startswith('/')
        if isinstance(yaml, str):
            yaml = {'input': yaml}

        assert isinstance(yaml, dict)
        assert 'input' in yaml
        assert yaml['input'] is None or isinstance(yaml['input'], str)

        super().__init__(name, yaml, parent)

        self.input = yaml['input']

        # TODO: Should the seed depend on white space? For now it does.
        if not self.manual:
            seed_value = self.config.random_salt + self.input
            self.seed = int(hashlib.sha512(seed_value.encode('utf-8')).hexdigest(), 16) % (2**31)

            commands = shlex.split(self.input)
            self.generator = commands[0]
            assert not self.generator.startswith('/')

            # NOTE: Still need to replace {seed} and {name}.
            self.arguments = commands[1:]


class Directory(Base):
    # Process yaml object for a directory.
    def __init__(self, name: str = None, yaml: dict = None, parent=None):
        if name is None:
            self.name = ''
            self.config = Config()
            self.path = Path('')
            self.numbered = False
            return

        assert is_directory(yaml)

        super().__init__(name, yaml, parent)

        if 'testdata.yaml' in yaml:
            self.testdata_yaml = yaml['testdata.yaml']
        else:
            self.testdata_yaml = None

        self.numbered = False
        # These field will be filled by parse().
        self.include = []
        self.data = []

        # Sanity checks for possibly empty data.
        if 'data' not in yaml: return
        data = yaml['data']
        if data is None: return
        assert isinstance(data, dict) or isinstance(data, list)
        if len(data) == 0: return

        if isinstance(data, dict):
            yaml['data'] = [data]
            assert parent.numbered is False

        if isinstance(data, list):
            self.numbered = True


class GeneratorConfig:
    ROOT_KEYS = [
            ('generators', []), ]

    def __init__(self, yaml_path: Path):
        if not yaml_path.is_file(): exit(1)

        yaml = yamllib.load(yaml_path.read_text(), Loader=yamllib.BaseLoader)

        assert isinstance(yaml, dict)
        yaml['type'] = 'directory'

        # Read root level configuration
        for key, default in self.ROOT_KEYS:
            if yaml and key in yaml:
                # TODO: Parse generators array to something more usable.
                setattr(self, key, yaml[key])
            else:
                setattr(self, key, default)

        next_number = 1
        # A map from directory paths `secret/testgroup` to Directory objects, used to resolve testcase
        # inclusion.
        data_dict = {}

        self.num_testcases = 0

        # Things that we'll need to build.
        self.generators_used = set()
        self.solutions_used = set()
        self.visualizers_used = set()

        # Main recursive parsing function.
        def parse(name, yaml, parent):
            nonlocal next_number, data_dict

            assert is_testcase(yaml) or is_directory(yaml)

            if is_testcase(yaml):
                t = Testcase(name, yaml, parent)
                assert t.path not in data_dict
                data_dict[t.path] = t

                self.num_testcases += 1
                if not t.manual: self.generators_used.add(t.generator)
                if t.config.solution: self.solutions_used.add(t.config.solution)
                if t.config.visualizer: self.visualizers_used.add(t.config.visualizer)

                return t

            assert is_directory(yaml)

            d = Directory(name, yaml, parent)
            assert d.path not in data_dict
            data_dict[d.path] = d

            def get_include(path: str) -> Directory:
                path = Path(path)
                assert path in data_dict
                return data_dict[path]

            if 'include' in yaml:
                self.include = [get_include(include) for include in yaml['include']]

            self.data = []

            if 'data' not in yaml: return d

            for dictionary in yaml['data']:
                if d.numbered:
                    number_prefix = str(next_number) + '-'
                    next_number += 1
                else:
                    number_prefix = ''

                for child_name, child_yaml in sorted(dictionary.items()):
                    if isinstance(child_name, int): child_name = str(child_name)
                    child_name = number_prefix + child_name
                    d.data.append(parse(child_name, child_yaml, d))

            return d

        self.root_dir = parse('', yaml, Directory())

        print(self.generators_used)


def test_generate(yaml_paths):
    GeneratorConfig(Path(yaml_paths[0]))
    exit(0)
