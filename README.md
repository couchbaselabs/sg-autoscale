
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

## Generate Cloudformation template

```
$ python src/sgautoscale_cloudformation_template.py
```

## Create Cloudformation Stack

You will need to first:

* Install AWS cli
* Set AWS credential env variables

Run this command and replace `YourStackName` and `YourKeyName` with the values that make sense for your setup:

```
$ aws cloudformation create-stack \
  --stack-name "YourStackName" \
  --template-body "file://generated/sgautoscale_cloudformation_template.json" \
  --region us-east-1 \
  --parameters ParameterKey=KeyName,ParameterValue=YourKeyName \
  --capabilities CAPABILITY_IAM
```

## Manual setup steps

### Add DNS entry for Couchbase Server

Go to Route53 update cb1.sgautoscale.couchbasemobile.com to point CNAME record to any of the Couchbase Servers

Open [http://cb1.sgautoscale.couchbasemobile.com:8091](http://cb1.sgautoscale.couchbasemobile.com:8091) and make sure you can login and the cluster looks healthy.


### Elastic Load Balancer DNS 

This is optional, but it creates a much cleaner URL to test against

1. Go to ELB and get the DNS entry
1. Go to Route53 update sgautoscale.couchbasemobile.com to point CNAME record to the ELB DNS

## Manually increase AutoScaleGroup instances

In the Web Admin UI:

1. Go to EC2 / Auto Scaling Groups
1. Click either the SG or SG Accel auto-scaling group
1. Under **Details** click the **Edit** button, and change the **Desired** to the number you want and hit **Save**


## Verify Elastic Load Balancer

```
$ curl http://sgautoscale.couchbasemobile.com:4984/
{"couchdb":"Welcome","vendor":{"name":"Couchbase Sync Gateway","version":1.4},"version":"Couchbase Sync Gateway/1.4(103;f7535d3)"}
```

## Instructions to setup ssh tunnels

This is required to push data back to Influx/Grafana host:

```
$ cd ~/Development/mobile-testkit
$ source setup.sh
$ python libraries/provision/generate_pools_json_from_aws.py --stackname yourstackname
$ emacs resources/pool.json   # go to AWS web UI and get public dns names of all autoscale instances and manually add, but will be fixed after [mobile-testkit/issues/995](https://github.com/couchbaselabs/mobile-testkit/issues/995)
$ python utilities/setup_ssh_tunnel.py --target-host s61103cnt72.sc.couchbase.com --target-port 8086  --remote-hosts-user ec2-user --remote-host-port 8086 --remote-hosts-file resources/pool.json
```

## Run load generator

1. Find the hostname of the load generator
1. ssh in and run sgload or gateload

### gateload

Write the following sample config to gateload.json

```
{
     "Hostname": "sgautoscale.couchbasemobile.com",
     "Port": 4984,
     "AdminPort": 4985,
     "Database": "db",
     "DocSize": 1024,
     "SendAttachment": false,
     "RampUpIntervalMs": 100000,
     "RunTimeMs": 1800000,
     "SleepTimeMs": 10000,
     "NumPullers": 3000,
     "NumPushers": 3000,
     "ChannelActiveUsers": 40,
     "ChannelConcurrentUsers": 40,
     "MinUserOffTimeMs": 0,
     "MaxUserOffTimeMs": 0,
     "Verbose": false,
     "LogRequests": false,
     "UserOffset": 115000,
     "AuthType": "basic",
     "Password": "password",
     "StatsdEnabled":true,
     "FeedType": "continuous",
     "StatsdEndpoint":"localhost:8125"
}
```

Run gateload via:

```
$ gateload -workload gateload.json
```


### sgload

```
$ cd go/bin
$ ./sgload gateload --createreaders --createwriters --numreaders 1000 --numwriters 1000 --numupdaters 1000 --writerdelayms 10000 --batchsize 10 --numchannels 10 --numdocs 1000000 --loglevel debug --sg-url http://sgautoscale.couchbasemobile.com:4984/db/ --expvarprogressenabled --statsdenabled --statsdendpoint localhost:8125
```

## View Grafana metrics

1. Go to grafana.couchbasemobile.com:3000
1. Choose the `telegraf` database from the pull down
1. Go to the time range you are interested in

## Regenerate cloudformation template (development)

If you make changes to `src/cloudformation_template.py`, you will need to regenerate the cloudformation template JSON via:

```
$ python src/cloudformation_template.py
```

after this, you should have an updated file in `generated/sgautoscale_cloudformation_template.json`








