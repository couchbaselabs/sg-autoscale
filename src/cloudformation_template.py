
# Python script to generate an AWS CloudFormation template json file

import collections
from troposphere import Ref, Template, Parameter, Tags, Base64, Join
import troposphere.autoscaling as autoscaling
from troposphere.elasticloadbalancing import LoadBalancer
from troposphere import GetAZs
import troposphere.ec2 as ec2
import troposphere.elasticloadbalancing as elb
from troposphere import iam

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
            'arn:aws:iam::aws:policy/CloudWatchFullAccess'
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
        instance.ImageId = "ami-1536e003"  # Couchbase Server 4.5 based on Centos7
        instance.InstanceType = couchbase_instance_type
        instance.SecurityGroups = [Ref(secGrpCouchbase)]
        instance.KeyName = Ref(keyname_param)
        instance.Tags = Tags(Name=name, Type="couchbaseserver")
        instance.IamInstanceProfile = Ref(instanceProfile)
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
        AvailabilityZones=GetAZs(""),  # Get all AZ's in current region (I think)
        HealthCheck=elb.HealthCheck(
            Target="HTTP:4984/",
            HealthyThreshold="5",
            UnhealthyThreshold="2",
            Interval="20",
            Timeout="15",
        ),
        Listeners=[
            elb.Listener(
                LoadBalancerPort="4984",
                InstancePort="4984",
                Protocol="HTTP",
                InstanceProtocol="HTTP",
            ),
        ],
        CrossZone=True,
        # SecurityGroups=[Ref(secGrpCouchbase)],  TODO: why doesn't this work?
        SecurityGroups=["sg-485ac631"],  # Hardcode ID of default VPC security group
        LoadBalancerName="SGAutoScaleLoadBalancer",
        Scheme="internet-facing",
    )
    t.add_resource(SGAutoScaleLoadBalancer)

    # SG AutoScaleGroup
    # ------------------------------------------------------------------------------------------------------------------
    SGLaunchConfiguration = autoscaling.LaunchConfiguration(
        "SGLaunchConfiguration",
        ImageId="ami-fc9544ea",
        KeyName=Ref(keyname_param),
        IamInstanceProfile=Ref(instanceProfile),
        InstanceType=sync_gateway_server_type,
        SecurityGroups=[Ref(secGrpCouchbase)],
        UserData=sgAndSgAccelUserData(),
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
        MaxSize=100,
        MinSize=0,
    )
    t.add_resource(SGAutoScalingGroup)

    # SG Accel AutoScaleGroup
    # ------------------------------------------------------------------------------------------------------------------
    SGAccelLaunchConfiguration = autoscaling.LaunchConfiguration(
        "SGAccelLaunchConfiguration",
        ImageId="ami-e69948f0",
        KeyName=Ref(keyname_param),
        IamInstanceProfile=Ref(instanceProfile),
        InstanceType=sync_gateway_server_type,
        SecurityGroups=[Ref(secGrpCouchbase)],
        UserData=sgAndSgAccelUserData(),
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
        MaxSize=100,
        MinSize=0,
    )
    t.add_resource(SGAccelAutoScalingGroup)



    # Load generator instances
    # ------------------------------------------------------------------------------------------------------------------
    for i in xrange(num_load_generators):
        name = "loadgenerator{}".format(i)
        instance = ec2.Instance(name)
        instance.ImageId = "ami-6d1c2007"  # centos7
        instance.InstanceType = load_generator_instance_type
        instance.SecurityGroups = [Ref(secGrpCouchbase)]
        instance.KeyName = Ref(keyname_param)
        instance.IamInstanceProfile = Ref(instanceProfile)
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

    return t.to_json()

# The "user data" launch script that runs on startup on SG and SG Accel EC2 instances.
# This uses "cloud-init" which is pre-installed on the EC2 instances, and the logs are
# available in /var/log/cloud-init-output.log
# ----------------------------------------------------------------------------------------------------------------------
def sgAndSgAccelUserData():
    return Base64(Join('', [
        '#!/bin/bash\n',
        'wget https://raw.githubusercontent.com/couchbaselabs/sg-autoscale/master/src/sg-launch.sh\n',
        'cat sg-launch.sh\n',
        'sudo python sg-launch.sh\n'
    ]))

# Main
# ----------------------------------------------------------------------------------------------------------------------
def main():

    Config = collections.namedtuple('Config', 'num_couchbase_servers couchbase_instance_type sync_gateway_server_type num_load_generators load_generator_instance_type')
    config = Config(
        num_couchbase_servers=3,
        couchbase_instance_type="m3.medium",
        sync_gateway_server_type="m3.medium",
        num_load_generators=1,
        load_generator_instance_type="m3.medium",
    )

    templ_json = gen_template(config)

    template_file_name = "cf_template.json"
    with open(template_file_name, 'w') as f:
        f.write(templ_json)

    print("Wrote cloudformation template: {}".format(template_file_name))


if __name__ == "__main__":
    main()
