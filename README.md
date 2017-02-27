
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

### Couchbase Server

1. Find the hostname of one of the Couchbase Server instances
1. Go to Web UI at `${hostname}:8091`
1. Set up initial node -- make sure it's using all available RAM, the defaults feel broken and suggesting a number that's way too low
1. Go to other Couchbase Server nodes and join that node
1. Rebalance
1. Add data-bucket and index-bucket
1. Go to Route53 update cb1.sgautoscale.couchbasemobile.com to point CNAME record to any of the Couchbase Servesr

Instead of doing this by hand, it can be done via couchbase-cli

```
$ ./couchbase-cli init-cluster # TODO: add instructions
$ ./couchbase-cli server-add -c ec2-54-89-145-30.compute-1.amazonaws.com --server-add ec2-54-237-29-75.compute-1.amazonaws.com -u Administrator -p password --server-add-username=Administrator --server-add-password=password
```

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

## Instructions to setup ssh tunnels

This is required to push data back to Influx/Grafana host:

```
$ python libraries/provision/generate_pools_json_from_aws.py --stackname yourstackname
$ emacs resources/pool.json   # go to AWS web UI and get public dns names of all autoscale instances and manually add
$ python utilities/setup_ssh_tunnel.py --target-host s61103cnt72.sc.couchbase.com --target-port 8086  --remote-hosts-user ec2-user --remote-host-port 8086 --remote-hosts-file resources/pool.json
```

## Run load generator

1. Find the hostname of the load generator
1. ssh in and run sgload or gateload

### sgload

```
$ cd go/bin
$ ./sgload gateload --createreaders --createwriters --numreaders 1000 --numwriters 1000 --numupdaters 1000 --writerdelayms 10000 --batchsize 10 --numchannels 10 --numdocs 1000000 --loglevel debug --sg-url http://sgautoscale.couchbasemobile.com:4984/db/ --expvarprogressenabled --statsdenabled --statsdendpoint localhost:8125
```

## Pushing from load generator to grafana


### ssh tunnel

```
$ ssh -o StrictHostKeyChecking=no ec2-user@ec2-54-89-204-209.compute-1.amazonaws.com -R 8086:s61103cnt72.sc.couchbase.com:8086 -N -f
```

### Telegraf


```
$ sudo yum install -y https://dl.influxdata.com/telegraf/releases/telegraf-1.0.0.x86_64.rpm
```

Update `/etc/telegraf/telegraf.conf` to uncomment these two lines:

```
[[inputs.statsd]]
   service_address = ":8125"
   allowed_pending_messages = 10000
```

Restart with

```
$ systemctl restart telegraf
```


## Regenerate cloudformation template

If you make changes to `src/cloudformation_template.py`, you will need to regenerate the cloudformation template JSON via:

```
$ python src/cloudformation_template.py
```

after this, you should have an updated file in `generated/sgautoscale_cloudformation_template.json`








