FROM ubuntu:16.04

USER root

MAINTAINER lmazuel

RUN apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys 417A0893

# Basic Ubuntu packages (libunwind for .NET)
RUN apt-get update && apt-get install -y curl git software-properties-common locales libunwind8

# NodeJS
RUN curl -sL https://deb.nodesource.com/setup_7.x | bash - && \
    apt-get update && apt-get install -y nodejs

# Python 3.6
RUN add-apt-repository ppa:jonathonf/python-3.6 && \
	apt-get update && \
	apt-get install -y python3.6

# Install pip for Python 3.6
RUN curl -sL https://bootstrap.pypa.io/get-pip.py | python3.6

# Autorest
RUN npm install -g autorest

# Python packages
COPY requirements.txt /tmp
RUN pip3.6 install -r /tmp/requirements.txt

# Set the locale to UTF-8
RUN locale-gen en_US.UTF-8  
ENV LANG en_US.UTF-8  
ENV LANGUAGE en_US:en  
ENV LC_ALL en_US.UTF-8  

COPY SwaggerToSdkMain.py /
COPY SwaggerToSdkCore.py /
COPY SwaggerToSdkLegacy.py /
COPY SwaggerToSdkNewCLI.py /
COPY markdown_support.py /

WORKDIR /git-restapi
ENTRYPOINT ["python3.6", "/SwaggerToSdkMain.py"]
