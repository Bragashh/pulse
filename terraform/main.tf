terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "eu-central-1"
}

# SSH key pair so Ansible can connect to the EC2s
resource "aws_key_pair" "pulse_key" {
  key_name   = "pulse-key"
  public_key = file("~/.ssh/id_rsa.pub")
}

# Security group — allows SSH and HTTP
resource "aws_security_group" "pulse_sg" {
  name        = "pulse-sg"
  description = "Allow SSH and HTTP"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Staging EC2
resource "aws_instance" "staging" {
  ami                    = "ami-0a628e1e89aaedf80"  # Ubuntu 24.04 eu-central-1
  instance_type          = "t3.micro"
  key_name               = aws_key_pair.pulse_key.key_name
  vpc_security_group_ids = [aws_security_group.pulse_sg.id]

  tags = {
    Name = "pulse-staging"
  }
}

# Production EC2
resource "aws_instance" "production" {
  ami                    = "ami-0a628e1e89aaedf80"  # Ubuntu 24.04 eu-central-1
  instance_type          = "t3.micro"
  key_name               = aws_key_pair.pulse_key.key_name
  vpc_security_group_ids = [aws_security_group.pulse_sg.id]

  tags = {
    Name = "pulse-production"
  }
}

# Output the IPs so Ansible can use them
output "staging_ip" {
  value = aws_instance.staging.public_ip
}

output "production_ip" {
  value = aws_instance.production.public_ip
}
