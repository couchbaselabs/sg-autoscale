
import urllib2
import json 
import subprocess
import os
import time
import sys
import argparse

"""
This script attempts to bootstrap this machine into a couchbase cluster using the
cbbootstrap REST API.

It assumes:

- The cbbootstrap REST api is available at CBBOOTSTRAP_API_URL
- Couchbase Server is installed locally, but not initialized

"""

# This is an AWS Lambda function running behind a API Gateway.  The code is available at https://github.com/couchbase/cbbootstrap
CBBOOTSTRAP_API_URL = "https://5e61vqxs5f.execute-api.us-east-1.amazonaws.com/Prod/cluster"

couchbase_server_bin_path = "/opt/couchbase/bin"
couchbase_server_admin_port = "8091"
couchbase_cli_abs_path = os.path.join(
    couchbase_server_bin_path,
    "couchbase-cli",
)
couchbase_server_bucket_type = "couchbase"
couchbase_server_bucket_replica = 1
        
class CouchbaseCluster:

    def __init__(self, cluster_id, node_ip_addr_or_hostname=""):
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

        self.CBBootstrapCreateOrJoin()
        if self.is_initial_node:
            self.Create()
        else:
            self.Join()


    def CBBootstrapCreateOrJoin(self):
        """
        Call out to the cbbootrap REST API and do a POST request to create or join
        a cluster
        """

        # POST request
        params = {
            'cluster_id': self.cluster_id,
            'node_ip_addr_or_hostname': self.node_ip_addr_or_hostname,
        }
        req = urllib2.Request(CBBOOTSTRAP_API_URL,
                              headers = {
                                  "Content-Type": "application/json",
                              },
                              data = json.dumps(params),  # Since adding data, automatically makes it a POST request
        )
        response = urllib2.urlopen(req)
        self.__cbbootstrap_load_properties_from_json_response(response)



    def CBBootstrapGetClusterInfo(self):
        """
        Given a cluster_id, query the cbbootrap rest API and find IP addr or hostname
        of initial couchbase server node
        """

        get_cluster_info_url = "{}/{}".format(CBBOOTSTRAP_API_URL, self.cluster_id)
        response = urllib2.urlopen(get_cluster_info_url)
        self.__cbbootstrap_load_properties_from_json_response(response)

    def CBBootstrapGetClusterInfoRetry(self):
        self.Retry(self.CBBootstrapGetClusterInfo)

    def __cbbootstrap_load_properties_from_json_response(self, json_response):

        data = json.load(json_response)
        print("Server response: {}".format(data))
        self.cluster_id = data["cluster_id"]
        self.initial_node_ip_addr_or_hostname = data["initial_node_ip_addr_or_hostname"]
        self.is_initial_node = data["is_initial_node"]


    def Create(self):

        self.WaitUntilLocalCouchbaseServerRunning()
        
        self.ClusterInit()

        # This is to prevent node-init failures if we try to call
        # node-init "too soon".  Since node-init hasn't been called, the
        # server-list command will return:
        #   ns_1@127.0.0.1 172.31.21.40:8091 healthy active
        self.WaitUntilNodeHealthy("127.0.0.1")

        # Workaround attempt for https://issues.couchbase.com/browse/MB-23079
        time.sleep(2)

        self.NodeInit()
        
    def ClusterInit(self):

        subprocess_args = [
            couchbase_cli_abs_path,
            "cluster-init",
            "-c",
            "{}:{}".format(self.node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(self.admin_user),
            "--password={}".format(self.admin_pass),
            "--cluster-port={}".format(couchbase_server_admin_port),
            "--cluster-ramsize={}".format(self._get_effective_ram_mb()),
            "--services=data",
        ]
        
        exec_subprocess(subprocess_args)


    def WaitUntilLocalCouchbaseServerRunning(self):
        self.Retry(self.LocalCouchbaseServerRunningOrRaise)

    def LocalCouchbaseServerRunningOrRaise(self):
        urllib2.urlopen('http://{}:{}'.format(self.node_ip_addr_or_hostname, couchbase_server_admin_port))
        
    def WaitUntilNodeHealthy(self, node_ip):
        def f():
            self.NodeHealthyOrRaise(node_ip)
            
        self.Retry(f)

    def NodeHealthyOrRaise(self, node_ip):
        subprocess_args = [
            couchbase_cli_abs_path,
            "server-list",
            "-c",
            "{}:{}".format(self.initial_node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(self.admin_user),
            "--password={}".format(self.admin_pass),
        ]
        output = exec_subprocess(subprocess_args)
        if node_ip not in output:
            raise Exception("Did not find {} in {}".format(node_ip, output))
        if "unhealthy" in output:
            raise Exception("Some nodes appear to be unhealthy: {}".format(output))
        
    def NodeInit(self):

        subprocess_args = [
            couchbase_cli_abs_path,
            "node-init",
            "-c",
            "{}:{}".format(self.node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(self.admin_user),
            "--password={}".format(self.admin_pass),
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
        
        self.WaitUntilLocalCouchbaseServerRunning()
        
        self.WaitUntilNodeHealthy(self.initial_node_ip_addr_or_hostname)  
        self.ServerAdd()
        self.WaitForNoRebalanceRunning()
        self.Rebalance()
        
    def ServerAdd(self):

        subprocess_args = [
            couchbase_cli_abs_path,
            "server-add",
            "-c",
            "{}:{}".format(self.initial_node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(self.admin_user),
            "--password={}".format(self.admin_pass),
            "--server-add={}".format(self.node_ip_addr_or_hostname),
            "--server-add-username={}".format(self.admin_user),
            "--server-add-password={}".format(self.admin_pass),
        ]
        
        exec_subprocess(subprocess_args)

    def WaitForNoRebalanceRunning(self):
        max_retries = 200
        for i in range(max_retries):
            
            if not self.IsRebalanceRunning():
                print("No rebalance running.  Finished waiting")
                return 

            print("Rebalance running, waiting 10 seconds")
            time.sleep(10)

    def IsRebalanceRunning(self):
        
        subprocess_args = [
            couchbase_cli_abs_path,
            "rebalance-status",
            "-c",
            "{}:{}".format(self.initial_node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(self.admin_user),
            "--password={}".format(self.admin_pass),
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
            "--user={}".format(self.admin_user),
            "--password={}".format(self.admin_pass),
        ]
        
        exec_subprocess(subprocess_args)

    def _get_total_ram_mb(self):
        """
        Get total ram -- taken from http://stackoverflow.com/questions/22102999/get-total-physical-memory-in-python
        """

        mem_bytes = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')  # e.g. 4015976448
        total_avail_ram_mb = mem_bytes / (1024. ** 2)

        print("total_avail_ram_mb: {}".format(total_avail_ram_mb))
        return total_avail_ram_mb

    def _get_effective_ram_mb(self):
        """ Return the amount of effective RAM ((total RAM * muliplier) - n1ql ram allocation)
        Given a total amount of ram

        TODO: duplicated from mobile-testkit couchbaseserver.py -- should be consolidated

        """

        # Leave 20% of RAM available for the underlying OS
        ram_multiplier = 0.80

        total_ram_mb = self._get_total_ram_mb()
        effective_avail_ram_mb = int(total_ram_mb * ram_multiplier)

        print("effective_avail_ram_mb: {}".format(effective_avail_ram_mb))
        return effective_avail_ram_mb

    def AddBucket(self, bucket_name, bucket_percent_ram):

        if not self.is_initial_node:
            print("Skipping adding bucket since this is not the initial node")
            return

        # Tries to avoid errors: "Cannot create buckets during rebalance"
        self.WaitForNoRebalanceRunning()
        
        if bucket_percent_ram < 0.0 or bucket_percent_ram > 1.0:
            raise Exception("invalid bucket_percent_ram: {}".format(bucket_percent_ram))
        
        bucket_ramsize = self._get_effective_ram_mb() * bucket_percent_ram

        subprocess_args = [
            couchbase_cli_abs_path,
            "bucket-create",
            "-c",
            "{}:{}".format(self.initial_node_ip_addr_or_hostname, couchbase_server_admin_port),
            "--user={}".format(self.admin_user),
            "--password={}".format(self.admin_pass),
            "--bucket-type={}".format(couchbase_server_bucket_type),
            "--bucket={}".format(bucket_name),
            "--bucket-ramsize={}".format(int(bucket_ramsize)),
            "--bucket-replica={}".format(couchbase_server_bucket_replica),
            "--wait"
        ]
        
        exec_subprocess(subprocess_args)
        

def exec_subprocess(subprocess_args):
    print("Calling Couchbase CLI with {}".format(" ".join(subprocess_args)))
    
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

def discover_initial_couchbase_server_ip(cluster_id):
    """
    Given a cluster-id, discover the ip address or hostname of the initial couchbase server node IP address.
    This will do a back off retry several times to wait for it to become available
    """

    cbCluster = CouchbaseCluster(
        cluster_id=cluster_id,
    )
    cbCluster.CBBootstrapGetClusterInfoRetry()
    return cbCluster.initial_node_ip_addr_or_hostname

        

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--cluster-id",
                        help="The cluster-id to use for cbbootstrap.  Should be as unique as possible, for example like an AWS stack ID ran through base64",
                        required=True)
    parser.add_argument("--node-ip-addr-or-hostname",
                        help="The ip address or hostname that will be recorded so that other couchbase servers or other components can connect to this node if it becomes initial node",
                        required=True)
    parser.add_argument("--admin-user",
                        help="The username of the Couchbase Server admin user to create or connect as",
                        required=True)
    parser.add_argument("--admin-pass",
                        help="The password of the Couchbase Server admin user to create or connect as",
                        required=True)

    args = parser.parse_args()

    # make sure the cluster-id doesn't contain invalid chars
    url_quoted_cluster_id = urllib2.quote(args.cluster_id, safe='')
    if url_quoted_cluster_id != args.cluster_id:
        raise Exception("The cluster-id {} appears to have characters unsafe for urls." +
                        " The url quoted version is {}.  Consider base64 encoding it".format(
                            args.cluster_id,
                            url_quoted_cluster_id))

    print("{} called with cluster_id {}, node_ip_addr_or_hostname {}, admin user {}".format(
        sys.argv[0],
        args.cluster_id,
        args.node_ip_addr_or_hostname,
        args.admin_user,
    ))

    cbCluster = CouchbaseCluster(
        cluster_id=args.cluster_id,
        node_ip_addr_or_hostname=args.node_ip_addr_or_hostname,
    )
    cbCluster.SetAdminCredentials(
        admin_user=args.admin_user,
        admin_pass=args.admin_pass,
    )

    # Call out to cbbootstrap API to figure out whether to create or join, then actually create or join
    cbCluster.CreateOrJoin()

    # Create buckets (TODO: these should be CLI arguments)
    cbCluster.AddBucket("data-bucket", 0.50)
    cbCluster.AddBucket("index-bucket", 0.50)


if __name__ == "__main__":
    main()

