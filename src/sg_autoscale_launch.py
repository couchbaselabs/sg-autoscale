#!/usr/bin/env python


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
            "server":"http://cb1.sgautoscale.couchbasemobile.com:8091",
            "bucket":"data-bucket",
            "channel_index":{
                "server":"http://cb1.sgautoscale.couchbasemobile.com:8091",
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
            "server":"http://cb1.sgautoscale.couchbasemobile.com:8091",
            "bucket":"data-bucket",
            "channel_index":{
                "server":"http://cb1.sgautoscale.couchbasemobile.com:8091",
                "bucket":"index-bucket",
                "writer":true
            }
        }
    },
    "cluster_config":{
        "server":"http://cb1.sgautoscale.couchbasemobile.com:8091",
        "bucket":"data-bucket",
        "data_dir":"."
    }
}
"""

from sg_launch import main
    
if __name__ == "__main__":

   main(sync_gateway_config, sg_accel_config)
