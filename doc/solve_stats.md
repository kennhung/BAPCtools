## Instructions to embed solve stats in the solution slides

1. Clone https://github.com/hex539/scoreboard 
2. `mkdir {contest_root}/solve_stats`
3. Run the following two commands from the root of the `scoreboard` repo, changing what needs changing:
   ```
   bazel run analysis:activity -- --url https://chipcie.ch.tudelft.nl --contest 4 --prefreeze  -l {username} -p {password} {contest_root}/solve_stats
   bazel run analysis:activity -- --url https://chipcie.ch.tudelft.nl --contest 4 --prefreeze  -l {username} -p {password} --solvestats > {contest_root}/solve_stats/problem_stats.tex
   ```
1. Run `bt solutions` from the contest directory.
