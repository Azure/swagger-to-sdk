FROM ubuntu:16.04

MAINTAINER lmazuel

RUN apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys 417A0893

RUN echo "deb [arch=amd64] https://apt-mo.trafficmanager.net/repos/dotnet-release/ trusty main" | tee /etc/apt/sources.list.d/dotnetdev.list && \
	curl -sL https://deb.nodesource.com/setup_6.x | sudo -E bash - \
	apt-get update && apt-get install -y \
		dotnet-dev-1.0.0-preview2.1-003177 \
		python3-pip \
		python3-dev \
		git \
		nodejs

# Autorest
RUN npm install -g autorest

# Python packages
COPY requirements.txt /tmp
RUN pip3 install -r /tmp/requirements.txt

# Set the locale to UTF-8
RUN locale-gen en_US.UTF-8  
ENV LANG en_US.UTF-8  
ENV LANGUAGE en_US:en  
ENV LC_ALL en_US.UTF-8  

COPY SwaggerToSdk.py /

WORKDIR /git-restapi
ENTRYPOINT ["python3", "/SwaggerToSdk.py"]
