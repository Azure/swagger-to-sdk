FROM ubuntu:16.04

MAINTAINER lmazuel

RUN apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys 417A0893

# Basic Ubuntu packages
RUN apt-get update && apt-get install -y curl git software-properties-common

# NodeJS
RUN curl -sL https://deb.nodesource.com/setup_6.x | bash - && \
    apt-get update && apt-get install -y nodejs && \
    npm install npm@latest -g

# Dotnet
RUN echo "deb [arch=amd64] https://apt-mo.trafficmanager.net/repos/dotnet-release/ xenial main" | tee /etc/apt/sources.list.d/dotnetdev.list && \
	apt-get update && apt-get install -y dotnet-dev-1.0.0-preview2.1-003177

# Python 3.6
RUN add-apt-repository ppa:jonathonf/python-3.6 && \
	apt-get update && \
	apt-get install -y python3.6

# Autorest
RUN npm install -g autorest
RUN autorest --help

# Python packages
COPY requirements.txt /tmp
RUN pip3.6 install -r /tmp/requirements.txt

# Set the locale to UTF-8
RUN locale-gen en_US.UTF-8  
ENV LANG en_US.UTF-8  
ENV LANGUAGE en_US:en  
ENV LC_ALL en_US.UTF-8  

COPY SwaggerToSdk.py /

WORKDIR /git-restapi
ENTRYPOINT ["python3.6", "/SwaggerToSdk.py"]
