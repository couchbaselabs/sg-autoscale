
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

## Manual setup steps

### Couchbase Server

1. Find the hostname of one of the Couchbase Server instances
1. Go to Web UI at `${hostname}:8091`
1. Set up initial node -- make sure it's using all available RAM, the defaults feel broken and suggesting a number that's way too low
1. Go to other Couchbase Server nodes and join that node
1. Rebalance
1. Add data-bucket and index-bucket
1. Go to Route53 update cb1.sgautoscale.couchbasemobile.com to point CNAME record to any of the Couchbase Servesr

### Elastic Load Balancer DNS 

This is optional, but it creates a much cleaner URL to test against

1. Go to ELB and get the DNS entry
1. Go to Route53 update sgautoscale.couchbasemobile.com to point CNAME record to the ELB DNS

## Manually increase AutoScaleGroup instances

Find the name of the auto-scale groups

```
$ aws --region us-east-1 autoscaling describe-auto-scaling-groups | grep -i AutoScalingGroupName | grep -v arn
            "AutoScalingGroupName": "TleydenSgAutoScale18-SGAccelAutoScalingGroup-ND5SFRFOOLO7",
            "AutoScalingGroupName": "TleydenSgAutoScale18-SGAutoScalingGroup-W72N3BNON5Q9",
```

Increase SG and SG Accel instances

```
$ aws --region us-east-1 autoscaling set-desired-capacity --auto-scaling-group-name TleydenSgAutoScale18-SGAccelAutoScalingGroup-ND5SFRFOOLO7 --desired-capacity 1
$ aws --region us-east-1 autoscaling set-desired-capacity --auto-scaling-group-name TleydenSgAutoScale18-SGAutoScalingGroup-W72N3BNON5Q9 --desired-capacity 1
```

## Verify Elastic Load Balancer

```
$ curl http://sgautoscale.couchbasemobile.com:4984/
{"couchdb":"Welcome","vendor":{"name":"Couchbase Sync Gateway","version":1.4},"version":"Couchbase Sync Gateway/1.4(103;f7535d3)"}
```

## Run load generator

1. Find the hostname of the load generator
1. ssh in and run sgload or gateload

### sgload

```
$ cd go/bin
$ ./sgload gateload --createreaders --createwriters --numreaders 100 --numwriters 100 --numupdaters 0 --writerdelayms 1000 --batchsize 10 --numchannels 10 --numdocs 1000 --loglevel debug --sg-url http://sgautoscale.couchbasemobile.com:4984/db/
```









