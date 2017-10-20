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
WORKDIR /opt

# pre-load dotnet framework runtime to slim down runtime effort
RUN npm install dotnet-2.0.0 
 
# Autorest 
RUN npm install autorest
RUN ln -s /opt/node_modules/.bin/autorest /usr/local/bin
 
# ensure autorest minimum version of the modeler
RUN autorest --use="@microsoft.azure/autorest.modeler@2.0.21" --allow-no-input

# Set the locale to UTF-8
RUN locale-gen en_US.UTF-8  
ENV LANG en_US.UTF-8  
ENV LANGUAGE en_US:en  
ENV LC_ALL en_US.UTF-8  

COPY setup.py /tmp
COPY swaggertosdk /tmp/swaggertosdk/
WORKDIR /tmp
RUN pip3.6 install .

WORKDIR /git-restapi
ENTRYPOINT ["python3.6", "-m", "swaggertosdk"]
