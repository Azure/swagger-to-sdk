# Scenario: Validate a OpenAPI definition file according to the ARM guidelines 

> see https://aka.ms/autorest

## Inputs

``` yaml 
input-file:
  - https://github.com/Azure/azure-rest-api-specs/blob/master/specification/compute/resource-manager/Microsoft.Compute/2017-03-30/compute.json
```

## Validation

This time, we not only want to generate code, we also want to validate.

``` yaml
azure-arm: true # enables validation messages
```

## Generation

Also generate for some languages.

``` yaml 
csharp:
  output-folder: CSharp
java:
  output-folder: Java
nodejs:
  output-folder: NodeJS
python:
  output-folder: Python
ruby:
  output-folder: Ruby
```