
Scripts and configuration to deploy Couchbase Sync Gateway + Sync Gateway Accelerator to AWS with the ability to scale horizontally via AutoScale Groups.

## Setup direnv

You first need to install [direnv](https://github.com/direnv/direnv)

Create an `.envrc` file with contents:

```
layout python
```

At this point `direnv` should prompt you:

```
direnv: error .envrc is blocked. Run `direnv allow` to approve its content.
```

and you should run:

```
$ direnv allow
```

## Setup Virtualenv

```
$ source setup.sh
```

## Generate cloudformation template

```
$ python src/cloudformation_template.py
```

## Create Cloudformation Stack

You will need to first:

* Install AWS cli
* Set AWS credential env variables

Run this command and replace `YourStackName` and `YourKeyName` with the values that make sense for your setup:

```
$ aws cloudformation create-stack \
  --stack-name "YourStackName" \
  --template-body "file://src/cf_template.json" \
  --region us-east-1 \
  --parameters ParameterKey=KeyName,ParameterValue=YourKeyName \
  --capabilities CAPABILITY_IAM
```

## Manually increase AutoScaleGroup instances

```
$ aws --region us-east-1 autoscaling set-desired-capacity --auto-scaling-group-name TleydenSgAutoScale9-SGAutoScalingGroup-JQXZ6OQ99X1B --desired-capacity 2
```



