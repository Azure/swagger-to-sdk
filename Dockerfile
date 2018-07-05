FROM ubuntu:18.04

USER root

LABEL maintainer="lmazuel"

# Basic Ubuntu packages + Ruby (libunwind for .NET)
RUN apt-get update && apt-get install -y curl git software-properties-common locales libunwind8 ruby bundler libpng-dev zlibc zlib1g zlib1g-dev nodejs npm python3-pip

# Update npm
RUN npm install npm -g

# Go 1.9
RUN add-apt-repository ppa:gophers/archive && \
	apt-get update && \
	apt-get install -y golang-1.9-go
ENV PATH="/usr/lib/go-1.9/bin:/root/go/bin:${PATH}"

# Go dep
RUN go get -u github.com/golang/dep/cmd/dep

# Autorest
WORKDIR /opt

# pre-load dotnet framework runtime to slim down runtime effort
RUN npm install dotnet-2.0.0

# Autorest
RUN npm install autorest@latest
RUN ln -s /opt/node_modules/.bin/autorest /usr/local/bin

# Set the locale to UTF-8
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8

COPY setup.py /tmp
COPY swaggertosdk /tmp/swaggertosdk/
WORKDIR /tmp
RUN python3 -m pip install .[rest]

WORKDIR /git-restapi
ENTRYPOINT ["python3.6", "-m", "swaggertosdk"]
