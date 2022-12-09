# NOTE: This installs the BAPCtools version from the GitHub master branch.
FROM ubuntu:jammy
MAINTAINER kennhuang@alum.ccu.edu.tw

RUN apt update
RUN apt upgrade

RUN DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt -y install tzdata

# Install build tools
RUN apt install -y \
	build-essential \
	gcc \
	pypy \
	pypy3 \
	default-jdk \
	kotlin

# Install Latex
RUN apt install -y \
	texlive \
	texlive-latex-extra \
	latexmk

# Install pip3
RUN apt install -y \
	wget
RUN wget https://bootstrap.pypa.io/get-pip.py
RUN python3 ./get-pip.py

# Install BAPC python deps
RUN pip install pyyaml colorama argcomplete ruamel.yaml questionary

COPY . /opt/bapctools

RUN ln -sfn /opt/bapctools/bin/tools.py /usr/bin/bt && \
	ln -sfn /opt/bapctools/third_party/checktestdata /usr/bin/checktestdata

RUN mkdir /data
WORKDIR /data
ENTRYPOINT ["/bin/bt"]
