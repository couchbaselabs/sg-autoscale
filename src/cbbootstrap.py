
import urllib2
import json 

"""

Usage example:

couchbase_cluster = cbbootstrap.CouchbaseCluster(cluster_id, node_hostname)
   couchbase_cluster.SetAdminCredentials(admin_user="Administrator", admin_pass="Password")
   couchbase_cluster.CreateOrJoin()
   couchbase_cluster.AddBucketIfMissing(
      Name="data-bucket",
      PercentRam=0.50,
   )
   couchbase_cluster.AddBucketIfMissing(
      Name="index-bucket",
      PercentRam=0.50,
   )
   couchbase_cluster.Rebalance()
"""

CBBOOTSTRAP_API_URL = "https://5e61vqxs5f.execute-api.us-east-1.amazonaws.com/Prod/cluster"

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

        params = {
            'cluster_id': self.cluster_id,
            'bodynode_ip_addr_or_hostname': self.node_ip_addr_or_hostname,
        }
        req = urllib2.Request(url,
                              headers = {
                                  "Content-Type": "application/json",
                              },
                              data = json.dumps(params),
        )
        response = urllib2.urlopen(req)
        data = json.load(response)   
        print("Server response: {}".format(data))



def main():
    cbCluster = CouchbaseCluster(
        cluster_id="MyCluster1",
        node_ip_addr_or_hostname="ec2-54-153-46-91.us-west-1.compute.amazonaws.com",
    )
    cbCluster.CreateOrJoin()


if __name__ == "__main__":
    main()

