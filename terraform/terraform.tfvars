# Configure the managed SPOT node group to maintain one t4g.large and scale out if needed.
# Include multiple instance types so AWS Spot has fallback options across families/architectures.
enable_spot_node_group = true
node_architecture      = "x86"
spot_instance_types    = ["t3.large"]
node_min_size          = 1
node_desired_size      = 1
node_max_size          = 4
region                 = "us-east-1"

# Uncomment and set to an existing EC2 key pair name to allow SSH access.
# ssh_key_name = "my-ec2-keypair"
