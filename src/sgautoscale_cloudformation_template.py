
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


    #
    # Parameters
    #
    keyname_param = t.add_parameter(Parameter(
        'KeyName', Type='String',
        Description='Name of an existing EC2 KeyPair to enable SSH access'
    ))
    couchbase_server_admin_user_param = t.add_parameter(Parameter(
        'CouchbaseServerAdminUserParam', Type='String',
        Description='The Couchbase Server Admin username'
    ))
    couchbase_server_admin_pass_param = t.add_parameter(Parameter(
        'CouchbaseServerAdminPassParam', Type='String',
        Description='The Couchbase Server Admin password'
    ))

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
        server_type = "couchbaseserver"
        name = "couchbaseserver{}".format(i)
        instance = ec2.Instance(name)
        instance.ImageId = config.couchbase_ami_id
        instance.InstanceType = couchbase_instance_type
        instance.SecurityGroups = [Ref(secGrpCouchbase)]
        instance.KeyName = Ref(keyname_param)
        instance.Tags = Tags(Name=name, Type=server_type)
        instance.IamInstanceProfile = Ref(instanceProfile)
        instance.UserData = userDataCouchbaseServer(
            config.build_repo_commit,
            config.sgautoscale_repo_commit,
        )
        instance.BlockDeviceMappings = [blockDeviceMapping(config, server_type)]
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

    if config.load_balancer_dns_enabled:
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
        UserData=userDataSyncGatewayOrAccel(config.build_repo_commit, config.sgautoscale_repo_commit),
        BlockDeviceMappings=[blockDeviceMapping(config, "syncgateway")]
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
        UserData=userDataSyncGatewayOrAccel(config.build_repo_commit, config.sgautoscale_repo_commit),
        BlockDeviceMappings=[blockDeviceMapping(config, "sgaccel")]
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
        server_type = "loadgenerator"
        name = "loadgenerator{}".format(i)
        instance = ec2.Instance(name)
        instance.ImageId = config.load_generator_ami_id
        instance.InstanceType = load_generator_instance_type
        instance.SecurityGroups = [Ref(secGrpCouchbase)]
        instance.KeyName = Ref(keyname_param)
        instance.IamInstanceProfile = Ref(instanceProfile)
        instance.UserData = userDataSyncGatewayOrAccel(config.build_repo_commit, config.sgautoscale_repo_commit)
        instance.Tags = Tags(Name=name, Type=server_type)
        instance.BlockDeviceMappings = [blockDeviceMapping(config, server_type)]

        t.add_resource(instance)

    # Outputs
    # ------------------------------------------------------------------------------------------------------------------
    if config.load_balancer_dns_enabled:
        t.add_output([
            Output(
                "SGAutoScaleLoadBalancerPublicDNS",
                Value=GetAtt(SGAutoScaleLoadBalancer, "DNSName")
            ),
        ])

    return t.to_json()


def blockDeviceMapping(config, server_type):
    return ec2.BlockDeviceMapping(
        DeviceName=config.block_device_name,
        Ebs=ec2.EBSBlockDevice(
            DeleteOnTermination=True,
            VolumeSize=config.block_device_volume_size_by_server_type[server_type],
            VolumeType=config.block_device_volume_type
        )
    )


# The "user data" launch script that runs on startup on SG and SG Accel EC2 instances.
# The output from this script is available on the ec2 instance in /var/log/cloud-init-output.log
# ----------------------------------------------------------------------------------------------------------------------
def userDataSyncGatewayOrAccel(build_repo_commit, sgautoscale_repo_commit):
    return Base64(Join('', [
        '#!/bin/bash\n',
        'wget https://raw.githubusercontent.com/tleyden/build/' + build_repo_commit + '/scripts/jenkins/mobile/ami/sg_launch.py\n',
        'wget https://raw.githubusercontent.com/couchbaselabs/sg-autoscale/' + sgautoscale_repo_commit + '/src/sg_autoscale_launch.py\n',
        'wget https://raw.githubusercontent.com/couchbaselabs/sg-autoscale/' + sgautoscale_repo_commit + '/src/cbbootstrap.py\n',
        'cat *.py\n',
        'python sg_autoscale_launch.py --stack-name ', Ref("AWS::StackId"), '\n',
        'ethtool -K eth0 sg off\n'  # Disable scatter / gather for eth0 (see http://bit.ly/1R25bbE)
    ]))

# The "user data" launch script that runs on startup on Couchbase Server instances
# The output from this script is available on the ec2 instance in /var/log/cloud-init-output.log
# ----------------------------------------------------------------------------------------------------------------------
def userDataCouchbaseServer(build_repo_commit, sgautoscale_repo_commit):

    # TODO
    """
    shell: echo 'for i in /sys/kernel/mm/*transparent_hugepage/enabled; do echo never > $i; done' >> /etc/rc.local
    shell: echo 'for i in /sys/kernel/mm/*transparent_hugepage/defrag; do echo never > $i; done' >> /etc/rc.local
    shell: for i in /sys/kernel/mm/*transparent_hugepage/enabled; do echo never > $i; done
    """

    return Base64(Join('', [
        '#!/bin/bash\n',
        'service couchbase-server status\n',
        'sleep 60\n',  # workaround for https://issues.couchbase.com/browse/MB-23081
        'service couchbase-server status\n',
        'wget https://raw.githubusercontent.com/tleyden/build/' + build_repo_commit + '/scripts/jenkins/mobile/ami/sg_launch.py\n',
        'wget https://raw.githubusercontent.com/couchbaselabs/sg-autoscale/' + sgautoscale_repo_commit + '/src/sg_autoscale_launch.py\n',
        'wget https://raw.githubusercontent.com/couchbaselabs/sg-autoscale/' + sgautoscale_repo_commit + '/src/cbbootstrap.py\n',
        'cat *.py\n',
        'python sg_autoscale_launch.py --stack-name ', Ref("AWS::StackId"), '\n',  # on couchbase server machines, only installs telegraf.
        'export public_dns_name=$(curl http://169.254.169.254/latest/meta-data/public-hostname)\n',
        'python cbbootstrap.py --cluster-id ', Ref("AWS::StackId"), ' --node-ip-addr-or-hostname ${public_dns_name} --admin-user ',  Ref("CouchbaseServerAdminUserParam"), ' --admin-pass ',  Ref("CouchbaseServerAdminPassParam"), '\n',
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
            'load_balancer_dns_enabled',
            'load_balancer_dns_hostname',
            'load_balancer_dns_hosted_zone_name',
            'block_device_name',
            'block_device_volume_size_by_server_type',
            'block_device_volume_type',
            'build_repo_commit',
            'sgautoscale_repo_commit',
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
        load_balancer_dns_enabled=False,
        load_balancer_dns_hostname="sgautoscale",
        load_balancer_dns_hosted_zone_name="couchbasemobile.com.",
        block_device_name="/dev/sda1",  # "/dev/sda1" for centos, /dev/xvda for amazon linux ami
        block_device_volume_size_by_server_type={"couchbaseserver": 200, "syncgateway": 25, "sgaccel": 25, "loadgenerator": 25},
        block_device_volume_type="gp2",
        build_repo_commit="master",
        sgautoscale_repo_commit="master",

    )

    templ_json = gen_template(config)

    template_file_name = "generated/sgautoscale_cloudformation_template.json"
    with open(template_file_name, 'w') as f:
        f.write(templ_json)

    print("Wrote cloudformation template: {}".format(template_file_name))


if __name__ == "__main__":
    main()
