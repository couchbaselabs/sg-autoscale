
import urllib2
import json 
import subprocess
import os
import time

"""

Usage example:

couchbase_cluster = cbbootstrap.CouchbaseCluster(cluster_id, node_hostname)
   couchbase_cluster.SetAdminCredentials(admin_user="Administrator", admin_pass="Password")
   couchbase_cluster.CreateOrJoin()
   couchbase_cluster.AddBucket(
      Name="data-bucket",
      PercentRam=0.50,
   )
   couchbase_cluster.AddBucket(
      Name="index-bucket",
      PercentRam=0.50,
   )
   couchbase_cluster.Rebalance()
"""

CBBOOTSTRAP_API_URL = "https://5e61vqxs5f.execute-api.us-east-1.amazonaws.com/Prod/cluster"

couchbase_server_bin_path = "/opt/couchbase/bin"
couchbase_server_admin_port = "8091"
couchbase_server_admin = "Administrator"
couchbase_server_password = "password"
couchbase_server_cluster_ram = int(13500)  # TODO: calculate this
couchbase_cli_abs_path = os.path.join(
    couchbase_server_bin_path,
    "couchbase-cli",
)
couchbase_server_bucket_type = "couchbase"
couchbase_server_bucket_replica = 1
        
class CouchbaseCluster:

    def __init__(self, cluster_id, node_ip_addr_or_hostname):
        self.cluster_id = cluster_id
        self.node_ip_addr_or_hostname = node_ip_addr_or_hostname

    def SetAdminCredentials(self, admin_user, admin_pass):
        self.admin_user = admin_user
        self.admin_pass = admin_pass
        
        
    def CreateOrJoin(self):

        """
        Call out to cbbootstrap REST API with cluster_id and hostname
        Depending on response, either create new cluster or join existing
        """

        self.LoadFromBootstrapAPI()
        if self.is_initial_node:
            self.Create()
        else:
            self.Join()


    def LoadFromBootstrapAPI(self):

        params = {
            'cluster_id': self.cluster_id,
            'bodynode_ip_addr_or_hostname': self.node_ip_addr_or_hostname,
        }
        req = urllib2.Request(CBBOOTSTRAP_API_URL,
                              headers = {
                                  "Content-Type": "application/json",
                              },
                              data = json.dumps(params),
        )
        response = urllib2.urlopen(req)
        data = json.load(response)
        print("Server response: {}".format(data))
        self.cluster_id = data["cluster_id"]
        self.initial_node_ip_addr_or_hostname = data["initial_node_ip_addr_or_hostname"]
        self.is_initial_node = data["is_initial_node"]

    def Create(self):
        self.ClusterInit()

        # This is to prevent node-init failures if we try to call
        # node-init "too soon".  Since node-init hasn't been called, the
        # server-list command will return:
        #   ns_1@127.0.0.1 172.31.21.40:8091 healthy active
        self.WaitUntilNodeHealthy("127.0.0.1")  

        self.NodeInit()
        
    def ClusterInit(self):

        subprocess_args = [
            couchbase_cli_abs_path,
            "cluster-init",
            "-c",
            "{}:{}".format(self.node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(couchbase_server_admin),
            "--password={}".format(couchbase_server_password),
            "--cluster-port={}".format(couchbase_server_admin_port),
            "--cluster-ramsize={}".format(couchbase_server_cluster_ram),
            "--services=data",
        ]
        
        exec_subprocess(subprocess_args)


    def WaitUntilNodeHealthy(self, node_ip):
        def f():
            self.NodeHealthyOrRaise(node_ip)
            
        self.Retry(f)

    def NodeHealthyOrRaise(self, node_ip):
        subprocess_args = [
            couchbase_cli_abs_path,
            "server-list",
            "-c",
            "{}:{}".format(self.node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(couchbase_server_admin),
            "--password={}".format(couchbase_server_password),
        ]
        output = exec_subprocess(subprocess_args)
        if node_ip not in output:
            raise Exception("Did not find {} in {}".format(node_ip, output))
        
    def NodeInit(self):

        subprocess_args = [
            couchbase_cli_abs_path,
            "node-init",
            "-c",
            "{}:{}".format(self.node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(couchbase_server_admin),
            "--password={}".format(couchbase_server_password),
            "--node-init-hostname={}".format(self.node_ip_addr_or_hostname),
        ]
        
        exec_subprocess(subprocess_args)


    def Retry(self, method):
        max_retries = 10
        for i in range(max_retries):

            try:
                method()
                return 
            except Exception as e:
                print("Got exception running {}.  Will retry".format(e))
                
            time.sleep(10)

        raise Exception("Gave up trying to run {}".format(method))


    def CreateRetry(self):
        self.Retry(self.Create)
        
    def JoinRetry(self):
        self.Retry(self.Join)
        
    def Join(self):
        self.ServerAdd()
        self.WaitForNoRebalanceRunning()
        self.Rebalance()
        
    def ServerAdd(self):

        subprocess_args = [
            couchbase_cli_abs_path,
            "server-add",
            "-c",
            "{}:{}".format(self.initial_node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(couchbase_server_admin),
            "--password={}".format(couchbase_server_password),
            "--server-add={}".format(self.node_ip_addr_or_hostname),
            "--server-add-username={}".format(couchbase_server_admin),
            "--server-add-password={}".format(couchbase_server_password),
        ]
        
        exec_subprocess(subprocess_args)

    def WaitForNoRebalanceRunning(self):
        max_retries = 10
        for i in range(max_retries):
            
            if not self.IsRebalanceRunning():
                print("No rebance running.  Finished waiting")
                return 

            print("Rebalance running, waiting 10 seconds")
            time.sleep(10)

    def IsRebalanceRunning(self):
        
        subprocess_args = [
            couchbase_cli_abs_path,
            "rebalance-status",
            "-c",
            "{}:{}".format(self.initial_node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(couchbase_server_admin),
            "--password={}".format(couchbase_server_password),
        ]
        
        output = exec_subprocess(subprocess_args)

        if "notRunning" in output:
            return False
        elif "running" in output:
            return True

        print("Warning: unexpected output for rebalance-status: {}".format(output))

        return False  
        
        
    def Rebalance(self):

        subprocess_args = [
            couchbase_cli_abs_path,
            "rebalance",
            "-c",
            "{}:{}".format(self.initial_node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(couchbase_server_admin),
            "--password={}".format(couchbase_server_password),
        ]
        
        exec_subprocess(subprocess_args)

    def AddBucket(self, bucket_name, bucket_percent_ram):

        if not self.is_initial_node:
            print("Skipping adding bucket since this is not the initial node")
            return 
        
        if bucket_percent_ram < 0.0 or bucket_percent_ram > 1.0:
            raise Exception("invalid bucket_percent_ram: {}".format(bucket_percent_ram))
        
        bucket_ramsize = couchbase_server_cluster_ram * bucket_percent_ram 

        subprocess_args = [
            couchbase_cli_abs_path,
            "bucket-create",
            "-c",
            "{}:{}".format(self.initial_node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(couchbase_server_admin),
            "--password={}".format(couchbase_server_password),
            "--bucket-type={}".format(couchbase_server_bucket_type),
            "--bucket={}".format(bucket_name),
            "--bucket-ramsize={}".format(int(bucket_ramsize)),
            "--bucket-replica={}".format(couchbase_server_bucket_replica),
            "--wait"
        ]
        
        exec_subprocess(subprocess_args)
        

def exec_subprocess(subprocess_args):

    print("Calling Couchbase CLI with: {}".format(subprocess_args))
    
    try:
        output = subprocess.check_output(subprocess_args, stderr=subprocess.STDOUT)
        print(output)
        return output 
    except subprocess.CalledProcessError as e:
        print(
            "Error calling subprocess with {}.  Return code: {}.  Output: {}".format(
                subprocess_args,
                e.returncode,
                e.output
            )
        )
        raise e

        
def fakeCreate():

    cbCluster = CouchbaseCluster(
        cluster_id="MyCluster1",
        node_ip_addr_or_hostname="ec2-54-153-46-91.us-west-1.compute.amazonaws.com",
    )

    cbCluster.initial_node_ip_addr_or_hostname = cbCluster.node_ip_addr_or_hostname
    cbCluster.is_initial_node = True
    cbCluster.Create()
    cbCluster.AddBucket("data-bucket", 0.50)
    cbCluster.AddBucket("index-bucket", 0.50)    

    
def fakeJoin():
    
    cbCluster = CouchbaseCluster(
        cluster_id="MyCluster1",
        node_ip_addr_or_hostname="ec2-54-215-201-127.us-west-1.compute.amazonaws.com",
    )

    cbCluster.initial_node_ip_addr_or_hostname = "ec2-54-153-46-91.us-west-1.compute.amazonaws.com"
    cbCluster.is_initial_node = False
    cbCluster.Join() 
        
def main():
    # fakeCreate()    
    fakeJoin()

if __name__ == "__main__":
    main()

