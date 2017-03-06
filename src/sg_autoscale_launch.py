#!/usr/bin/env python

import sg_launch
import os
import re
import socket
import argparse
import cbbootstrap
from string import Template

# If you are running Sync Gateway, customize your configuration here
sync_gateway_config = """
{
    "log":[
        "HTTP+"
    ],
    "adminInterface":"0.0.0.0:4985",
    "interface":"0.0.0.0:4984",
    "databases":{
        "db":{
            "server":"http://$couchbase_server_ip:8091",
            "bucket":"data-bucket",
            "channel_index":{
                "server":"http://$couchbase_server_ip:8091",
                "bucket":"index-bucket",
                "writer":false
            },
            "users":{
                "GUEST":{
                    "disabled":false,
                    "admin_channels":[
                        "*"
                    ]
                }
            }
        }
    }
}
"""

# If you are running Sync Gateway Acceletor, customize your configuration here
sg_accel_config = """
{
    "log":[
        "HTTP+"
    ],
    "adminInterface":"0.0.0.0:4985",
    "interface":"0.0.0.0:4984",
    "databases":{
        "default":{
            "server":"http://$couchbase_server_ip:8091",
            "bucket":"data-bucket",
            "channel_index":{
                "server":"http://$couchbase_server_ip:8091",
                "bucket":"index-bucket",
                "writer":true
            }
        }
    },
    "cluster_config":{
        "server":"http://$couchbase_server_ip:8091",
        "bucket":"data-bucket",
        "data_dir":"."
    }
}
"""


   
def install_telegraf(server_type):
   
   """

   This is needed to push metrics to influx/grafana instance that is in the Couchbase VPN
   
   
   Modify values in config (jinja template) .. but for hostname just use the default machine hostname, possibly prefixed with lg$hostname or sg$hostname
   Overwrite default telegraf config
   Restart telegraf
   """

   # Install default telegraf
   os.system("sudo yum install -y https://dl.influxdata.com/telegraf/releases/telegraf-1.0.0.x86_64.rpm")

   # Download hacked telegraf binary from mobile-testkit repo
   os.system("wget https://github.com/couchbaselabs/mobile-testkit/raw/master/libraries/provision/ansible/playbooks/files/telegraf -O /usr/bin/telegraf")

   # Download appropriate config from mobile-testkit repo
   telegraf_config = "error"
   hostname_prefix = "error"
   if server_type is sg_launch.SERVER_TYPE_SYNC_GATEWAY:
      telegraf_config = "telegraf-sync-gateway.conf"
      hostname_prefix = "sg"
   elif server_type is sg_launch.SERVER_TYPE_SG_ACCEL:
      telegraf_config = "telegraf-sg-accel.conf"
      hostname_prefix = "ac"
   elif server_type is sg_launch.SERVER_TYPE_LOAD_GEN:
      telegraf_config = "telegraf-gateload.conf"
      hostname_prefix = "lg"      
   elif server_type is sg_launch.SERVER_TYPE_COUCHBASE_SERVER:
       telegraf_config = "telegraf-couchbase-server.conf"
       hostname_prefix = "cbs"             
   else:
      raise Exception("Unknown server type: {}".format(server_type))
   os.system("wget https://raw.githubusercontent.com/couchbaselabs/mobile-testkit/master/libraries/provision/ansible/playbooks/files/{}".format(telegraf_config))

   # Modify values in config -- it's a jinja2 template, but just shitegile it and use regex
   telegraf_config_content = open(telegraf_config).read()

   # Replace {{ influx_url }}
   telegraf_config_content = re.sub(
      "{{ influx_url }}",
      "http://localhost:8086",
      telegraf_config_content,
   )

   # Replace {{ grafana_db }}
   telegraf_config_content = re.sub(
      "{{ grafana_db }}",
      "telegraf",
      telegraf_config_content,
   )

   # Replace {{ inventory_hostname }} with something like sgip-172-31-2-81 or lgip-172-31-2-81
   hostname = "{}{}".format(hostname_prefix, socket.gethostname())
   telegraf_config_content = re.sub(
      "{{ inventory_hostname }}",
      hostname,
      telegraf_config_content,
   )

   # Write out the config to destination
   telegraf_config_dest = "/etc/telegraf/telegraf.conf"
   if os.path.exists(telegraf_config_dest):
      os.remove(telegraf_config_dest)
   with open(telegraf_config_dest, 'w') as f:
      f.write(telegraf_config_content)
   print("Wrote updated content to {}.  Content: {}".format(telegraf_config_dest, telegraf_config_content))

   # Restart telegraf
   os.system("service telegraf restart")


def relaunch_sg_with_custom_config(stack_name):

    # Use cbbootrap to call REST API to discover the IP address of the initial couchbase server node
    couchbase_server_ip = cbbootstrap.discover_initial_couchbase_server_ip(stack_name)

    template = Template(sync_gateway_config)
    sync_gateway_config_rendered = template.substitute(couchbase_server_ip=couchbase_server_ip)

    template = Template(sg_accel_config)
    sg_accel_config_rendered = template.substitute(couchbase_server_ip=couchbase_server_ip)

    sg_launch.main(sync_gateway_config_rendered, sg_accel_config_rendered)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--stack-name", help="The name of the cloudformation stack, so that cbbootstrap can discover couchbase server IP address", required=True)
    args = parser.parse_args()

    server_type = sg_launch.discover_server_type()

    # For sync gateways, relaunch sync gateway with correct config.
    if sg_launch.is_sync_gateway_or_accel(server_type):
        relaunch_sg_with_custom_config(args.stack_name)

    install_telegraf(server_type)


   
   
