
# Python script to generate an AWS CloudFormation template json file

import collections
from troposphere import Ref, Template, Parameter, Tags, Base64, Join, GetAtt, Output
import troposphere.autoscaling as autoscaling
from troposphere.elasticloadbalancing import LoadBalancer
from troposphere import GetAZs
import troposphere.ec2 as ec2
import troposphere.elasticloadbalancing as elb
from troposphere import iam
from troposphere.route53 import RecordSetType

def gen_template(config):

    num_couchbase_servers = config.num_couchbase_servers
    couchbase_instance_type = config.couchbase_instance_type
    sync_gateway_server_type = config.sync_gateway_server_type
    num_load_generators = config.num_load_generators
    load_generator_instance_type = config.load_generator_instance_type


    t = Template()
    t.add_description(
        'An Ec2-classic stack with Sync Gateway + Accelerator + Couchbase Server with horizontally scalable AutoScaleGroup'
    )

    # Security Group + Launch Keypair
    # ------------------------------------------------------------------------------------------------------------------
    def createCouchbaseSecurityGroups(t):

        # Couchbase security group
        secGrpCouchbase = ec2.SecurityGroup('CouchbaseSecurityGroup')
        secGrpCouchbase.GroupDescription = "Allow access to Couchbase Server"
        secGrpCouchbase.SecurityGroupIngress = [
            ec2.SecurityGroupRule(
                IpProtocol="tcp",
                FromPort="22",
                ToPort="22",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(
                IpProtocol="tcp",
                FromPort="8091",
                ToPort="8091",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(   # sync gw user port
                IpProtocol="tcp",
                FromPort="4984",
                ToPort="4984",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(   # sync gw admin port
                IpProtocol="tcp",
                FromPort="4985",
                ToPort="4985",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(   # expvars
                IpProtocol="tcp",
                FromPort="9876",
                ToPort="9876",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(   # couchbase server
                IpProtocol="tcp",
                FromPort="4369",
                ToPort="4369",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(   # couchbase server
                IpProtocol="tcp",
                FromPort="5984",
                ToPort="5984",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(   # couchbase server
                IpProtocol="tcp",
                FromPort="8092",
                ToPort="8092",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(   # couchbase server
                IpProtocol="tcp",
                FromPort="11209",
                ToPort="11209",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(   # couchbase server
                IpProtocol="tcp",
                FromPort="11210",
                ToPort="11210",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(   # couchbase server
                IpProtocol="tcp",
                FromPort="11211",
                ToPort="11211",
                CidrIp="0.0.0.0/0",
            ),
            ec2.SecurityGroupRule(   # couchbase server
                IpProtocol="tcp",
                FromPort="21100",
                ToPort="21299",
                CidrIp="0.0.0.0/0",
            )

        ]

        # Add security group to template
        t.add_resource(secGrpCouchbase)

        return secGrpCouchbase

    #
    # Parameters
    #
    keyname_param = t.add_parameter(Parameter(
        'KeyName', Type='String',
        Description='Name of an existing EC2 KeyPair to enable SSH access'
    ))

    secGrpCouchbase = createCouchbaseSecurityGroups(t)

    # EC2 Instance profile + Mobile Testkit Role to allow pushing to CloudWatch Logs
    # ------------------------------------------------------------------------------------------------------------------

    # Create an IAM Role to give the EC2 instance permissions to
    # push Cloudwatch Logs, which avoids the need to bake in the
    # AWS_KEY + AWS_SECRET_KEY into an ~/.aws/credentials file or
    # env variables
    mobileTestKitRole = iam.Role(
        'MobileTestKit',
        ManagedPolicyArns=[
            'arn:aws:iam::aws:policy/CloudWatchFullAccess',
            'arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess',
        ],
        AssumeRolePolicyDocument={
            'Version': '2012-10-17',
            'Statement': [{
                'Action': 'sts:AssumeRole',
                'Principal': {'Service': 'ec2.amazonaws.com'},
                'Effect': 'Allow',
            }]
        }
    )
    t.add_resource(mobileTestKitRole)

    # The InstanceProfile instructs the EC2 instance to use
    # the mobileTestKitRole created above.  It will be referenced
    # in the instance.IamInstanceProfile property for all EC2 instances created
    instanceProfile = iam.InstanceProfile(
        'EC2InstanceProfile',
        Roles=[Ref(mobileTestKitRole)],
    )
    t.add_resource(instanceProfile)

    # Couchbase Server Instances
    # ------------------------------------------------------------------------------------------------------------------
    for i in xrange(num_couchbase_servers):
        name = "couchbaseserver{}".format(i)
        instance = ec2.Instance(name)
        instance.ImageId = config.couchbase_ami_id
        instance.InstanceType = couchbase_instance_type
        instance.SecurityGroups = [Ref(secGrpCouchbase)]
        instance.KeyName = Ref(keyname_param)
        instance.Tags = Tags(Name=name, Type="couchbaseserver")
        instance.IamInstanceProfile = Ref(instanceProfile)
        instance.UserData = userDataCouchbaseServer()
        instance.BlockDeviceMappings = [
            ec2.BlockDeviceMapping(
                DeviceName="/dev/sda1",
                Ebs=ec2.EBSBlockDevice(
                    DeleteOnTermination=True,
                    VolumeSize=200,
                    VolumeType="gp2"
                )
            )
        ]
        t.add_resource(instance)


    # Elastic Load Balancer (ELB)
    # ------------------------------------------------------------------------------------------------------------------
    SGAutoScaleLoadBalancer = LoadBalancer(
        "SGAutoScaleLoadBalancer",
        ConnectionDrainingPolicy=elb.ConnectionDrainingPolicy(
            Enabled=True,
            Timeout=120,
        ),
        ConnectionSettings=elb.ConnectionSettings(
            IdleTimeout=3600,  # 1 hour to help avoid 504 GATEWAY_TIMEOUT for continuous changes feeds
        ),
        AvailabilityZones=GetAZs(""),  # Get all AZ's in current region (I think)
        HealthCheck=elb.HealthCheck(
            Target="HTTP:4984/",
            HealthyThreshold="2",
            UnhealthyThreshold="2",
            Interval="5",
            Timeout="3",
        ),
        Listeners=[
            elb.Listener(
                LoadBalancerPort="4984",
                InstancePort="4984",
                Protocol="HTTP",
                InstanceProtocol="HTTP",
            ),
            elb.Listener(
                LoadBalancerPort="4985",
                InstancePort="4985",
                Protocol="HTTP",
                InstanceProtocol="HTTP",
            ),
        ],
        CrossZone=True,
        SecurityGroups=[GetAtt("CouchbaseSecurityGroup", "GroupId")],
        LoadBalancerName=Join('',["SGAS-", Ref("AWS::StackName")]),
        Scheme="internet-facing",
    )
    t.add_resource(SGAutoScaleLoadBalancer)

    t.add_resource(
        RecordSetType(
            title="SgAutoScaleDNS",
            ResourceRecords=[
                GetAtt(SGAutoScaleLoadBalancer, "DNSName")
            ],
            TTL="900",
            Name="{}.{}".format(config.load_balancer_dns_hostname, config.load_balancer_dns_hosted_zone_name),
            HostedZoneName=config.load_balancer_dns_hosted_zone_name,
            Type="CNAME",
        )
    )

    # SG AutoScaleGroup
    # ------------------------------------------------------------------------------------------------------------------
    SGLaunchConfiguration = autoscaling.LaunchConfiguration(
        "SGLaunchConfiguration",
        ImageId=config.sync_gateway_ami_id,
        KeyName=Ref(keyname_param),
        IamInstanceProfile=Ref(instanceProfile),
        InstanceType=sync_gateway_server_type,
        SecurityGroups=[Ref(secGrpCouchbase)],
        UserData=userDataSyncGatewayOrAccel(),
        BlockDeviceMappings=[
            ec2.BlockDeviceMapping(
                DeviceName="/dev/sda1",
                Ebs=ec2.EBSBlockDevice(
                    DeleteOnTermination=True,
                    VolumeSize=25,
                    VolumeType="gp2"
                )
            )
        ]
    )
    t.add_resource(SGLaunchConfiguration)

    SGAutoScalingGroup = autoscaling.AutoScalingGroup(
        "SGAutoScalingGroup",
        AvailabilityZones=GetAZs(""),  # Get all AZ's in current region (I think)
        LaunchConfigurationName=Ref(SGLaunchConfiguration),
        LoadBalancerNames=[Ref(SGAutoScaleLoadBalancer)],
        Tags=[
            autoscaling.Tag(key="Type", value="syncgateway", propogate=True),
            autoscaling.Tag(key="Name", value="syncgateway_autoscale_instance", propogate=True),
        ],
        MaxSize=100,
        MinSize=0,
    )
    t.add_resource(SGAutoScalingGroup)

    # SG Accel AutoScaleGroup
    # ------------------------------------------------------------------------------------------------------------------
    SGAccelLaunchConfiguration = autoscaling.LaunchConfiguration(
        "SGAccelLaunchConfiguration",
        ImageId=config.sg_accel_ami_id,
        KeyName=Ref(keyname_param),
        IamInstanceProfile=Ref(instanceProfile),
        InstanceType=sync_gateway_server_type,
        SecurityGroups=[Ref(secGrpCouchbase)],
        UserData=userDataSyncGatewayOrAccel(),
        BlockDeviceMappings=[
            ec2.BlockDeviceMapping(
                DeviceName="/dev/sda1",
                Ebs=ec2.EBSBlockDevice(
                    DeleteOnTermination=True,
                    VolumeSize=25,
                    VolumeType="gp2"
                )
            )
        ]
    )
    t.add_resource(SGAccelLaunchConfiguration)

    SGAccelAutoScalingGroup = autoscaling.AutoScalingGroup(
        "SGAccelAutoScalingGroup",
        AvailabilityZones=GetAZs(""),  # Get all AZ's in current region (I think)
        LaunchConfigurationName=Ref(SGAccelLaunchConfiguration),
        Tags=[
            autoscaling.Tag(key="Type", value="sgaccel", propogate=True),
            autoscaling.Tag(key="Name", value="sgaccel_autoscale_instance", propogate=True),
        ],
        MaxSize=100,
        MinSize=0,
    )
    t.add_resource(SGAccelAutoScalingGroup)



    # Load generator instances
    # ------------------------------------------------------------------------------------------------------------------
    for i in xrange(num_load_generators):
        name = "loadgenerator{}".format(i)
        instance = ec2.Instance(name)
        instance.ImageId = config.load_generator_ami_id
        instance.InstanceType = load_generator_instance_type
        instance.SecurityGroups = [Ref(secGrpCouchbase)]
        instance.KeyName = Ref(keyname_param)
        instance.IamInstanceProfile = Ref(instanceProfile)
        instance.UserData = userDataSyncGatewayOrAccel()
        instance.Tags = Tags(Name=name, Type="loadgenerator")
        instance.BlockDeviceMappings = [
            ec2.BlockDeviceMapping(
                DeviceName="/dev/sda1",
                Ebs=ec2.EBSBlockDevice(
                    DeleteOnTermination=True,
                    VolumeSize=25,
                    VolumeType="gp2"
                )
            )
        ]

        t.add_resource(instance)

    # Outputs
    # ------------------------------------------------------------------------------------------------------------------
    t.add_output([
        Output(
            "SGAutoScaleLoadBalancerPublicDNS",
            Value=GetAtt(SGAutoScaleLoadBalancer, "DNSName")
        ),
    ])

    return t.to_json()

# The "user data" launch script that runs on startup on SG and SG Accel EC2 instances.
# The output from this script is available on the ec2 instance in /var/log/cloud-init-output.log
# ----------------------------------------------------------------------------------------------------------------------
def userDataSyncGatewayOrAccel():
    return Base64(Join('', [
        '#!/bin/bash\n',
        'wget https://raw.githubusercontent.com/tleyden/build/master/scripts/jenkins/mobile/ami/sg_launch.py\n',
        'wget https://raw.githubusercontent.com/couchbaselabs/sg-autoscale/master/src/sg_autoscale_launch.py\n',
        'wget https://raw.githubusercontent.com/couchbaselabs/sg-autoscale/master/src/cbbootstrap.py\n',
        'cat *.py\n',
        'python sg_autoscale_launch.py --stack-name ', Base64(Ref("AWS::StackId")), '\n',
        'ethtool -K eth0 sg off\n'  # Disable scatter / gather for eth0 (see http://bit.ly/1R25bbE)
    ]))

# The "user data" launch script that runs on startup on Couchbase Server instances
# The output from this script is available on the ec2 instance in /var/log/cloud-init-output.log
# ----------------------------------------------------------------------------------------------------------------------
def userDataCouchbaseServer():

    # TODO
    """
    shell: echo 'for i in /sys/kernel/mm/*transparent_hugepage/enabled; do echo never > $i; done' >> /etc/rc.local
    shell: echo 'for i in /sys/kernel/mm/*transparent_hugepage/defrag; do echo never > $i; done' >> /etc/rc.local
    shell: for i in /sys/kernel/mm/*transparent_hugepage/enabled; do echo never > $i; done
    """

    return Base64(Join('', [
        '#!/bin/bash\n',
        'sleep 60\n',  # workaround for https://issues.couchbase.com/browse/MB-23081
        'wget https://raw.githubusercontent.com/tleyden/build/master/scripts/jenkins/mobile/ami/sg_launch.py\n',
        'wget https://raw.githubusercontent.com/couchbaselabs/sg-autoscale/master/src/sg_autoscale_launch.py\n',
        'wget https://raw.githubusercontent.com/couchbaselabs/sg-autoscale/master/src/cbbootstrap.py\n',
        'cat *.py\n',
        'python sg_autoscale_launch.py --stack-name ', Base64(Ref("AWS::StackId")), '\n',  # on couchbase server machines, only installs telegraf.
        'export public_dns_name=$(curl http://169.254.169.254/latest/meta-data/public-hostname)\n',
        'python cbbootstrap.py ', Base64(Ref("AWS::StackId")), ' ${public_dns_name}\n',
        'ethtool -K eth0 sg off\n'  # Disable scatter / gather for eth0 (see http://bit.ly/1R25bbE)
    ]))

# Main
# ----------------------------------------------------------------------------------------------------------------------
def main():

    Config = collections.namedtuple(
        'Config',
        " ".join([
            'num_couchbase_servers',
            'couchbase_instance_type',
            'sync_gateway_server_type',
            'num_load_generators',
            'load_generator_instance_type',
            'couchbase_ami_id',
            'sync_gateway_ami_id',
            'sg_accel_ami_id',
            'load_generator_ami_id',
            'load_balancer_dns_hostname',
            'load_balancer_dns_hosted_zone_name',
        ]),
    )

    region = "us-east-1"  # TODO: make cli parameter

    # Generated via http://uberjenkins.sc.couchbase.com/view/Build/job/couchbase-server-ami/
    couchbase_ami_ids_per_region = {
        "us-east-1": "ami-d8f029ce",
        "us-west-1": "ami-f6b2ec96"
    }

    # Generated via http://uberjenkins.sc.couchbase.com/view/Build/job/sync-gateway-ami/
    sync_gateway_ami_ids_per_region = {
        "us-east-1": "ami-53924045",
        "us-west-1": "ami-f68bd596"
    }

    # Generated via http://uberjenkins.sc.couchbase.com/view/Build/job/sg-accel-ami/
    sg_accel_ami_ids_per_region = {
        "us-east-1": "ami-00914316",
        "us-west-1": "ami-298dd349"
    }

    # Generated via http://uberjenkins.sc.couchbase.com/view/Build/job/sg-load-generator-ami/
    load_generator_ami_ids_per_region = {
        "us-east-1": "ami-3d6ebe2b",
        "us-west-1": "ami-0d8bd56d"
    }

    config = Config(
        num_couchbase_servers=6,
        couchbase_instance_type="c3.2xlarge",
        couchbase_ami_id=couchbase_ami_ids_per_region[region],
        sync_gateway_server_type="c3.2xlarge",
        sync_gateway_ami_id=sync_gateway_ami_ids_per_region[region],
        sg_accel_ami_id=sg_accel_ami_ids_per_region[region],
        num_load_generators=1,
        load_generator_instance_type="c3.2xlarge",
        load_generator_ami_id=load_generator_ami_ids_per_region[region],
        load_balancer_dns_hostname="sgautoscale",
        load_balancer_dns_hosted_zone_name="couchbasemobile.com.",
    )

    templ_json = gen_template(config)

    template_file_name = "generated/sgautoscale_cloudformation_template.json"
    with open(template_file_name, 'w') as f:
        f.write(templ_json)

    print("Wrote cloudformation template: {}".format(template_file_name))


if __name__ == "__main__":
    main()
