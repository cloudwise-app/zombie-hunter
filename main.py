#!/usr/bin/env python3
"""
Zombie Hunter - AWS Resource Cleanup Tool
Finds unattached EBS volumes and idle Elastic IPs
"""

import json
import boto3
import click
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError
from rich.console import Console
from rich.table import Table
from rich.text import Text


class ZombieHunter:
    def __init__(self, bedrock_region='us-east-1'):
        self.session = boto3.Session()
        self.regions = self._get_regions()
        self.bedrock_region = bedrock_region
        self.console = Console()
    
    def _get_regions(self):
        """Get all available EC2 regions"""
        try:
            ec2 = self.session.client('ec2', region_name='us-east-1')
            response = ec2.describe_regions()
            return [region['RegionName'] for region in response['Regions']]
        except Exception as e:
            click.echo(f"Error getting regions: {e}", err=True)
            return ['us-east-1']  # fallback to default region
    
    def find_unattached_volumes(self, region):
        """Find unattached EBS volumes in a region"""
        try:
            ec2 = self.session.client('ec2', region_name=region)
            response = ec2.describe_volumes(
                Filters=[{'Name': 'status', 'Values': ['available']}]
            )
            
            volumes = []
            for volume in response['Volumes']:
                volumes.append({
                    'resource_type': 'ebs_volume',
                    'resource_id': volume['VolumeId'],
                    'size': volume['Size'],
                    'region': region,
                    'tags': {tag['Key']: tag['Value'] for tag in volume.get('Tags', [])},
                    'cost_estimate': self._estimate_ebs_cost(volume['Size'], volume['VolumeType'])
                })
            
            return volumes
        except ClientError as e:
            click.echo(f"Error in region {region}: {e}", err=True)
            return []
    
    def find_idle_elastic_ips(self, region):
        """Find unassociated Elastic IPs in a region"""
        try:
            ec2 = self.session.client('ec2', region_name=region)
            response = ec2.describe_addresses()
            
            idle_ips = []
            for address in response['Addresses']:
                # EIP is idle if it has no InstanceId or NetworkInterfaceId
                if 'InstanceId' not in address and 'NetworkInterfaceId' not in address:
                    idle_ips.append({
                        'resource_type': 'elastic_ip',
                        'resource_id': address['AllocationId'],
                        'public_ip': address['PublicIp'],
                        'region': region,
                        'tags': {tag['Key']: tag['Value'] for tag in address.get('Tags', [])},
                        'cost_estimate': self._estimate_eip_cost()
                    })
            
            return idle_ips
        except ClientError as e:
            click.echo(f"Error in region {region}: {e}", err=True)
            return []
    
    def hunt_zombies(self, regions=None):
        """Hunt for zombie resources across regions"""
        if regions is None:
            regions = self.regions
        
        all_zombies = []
        
        for region in regions:
            click.echo(f"Scanning region: {region}")
            
            # Find unattached volumes
            volumes = self.find_unattached_volumes(region)
            all_zombies.extend(volumes)
            
            # Find idle Elastic IPs
            ips = self.find_idle_elastic_ips(region)
            all_zombies.extend(ips)
        
        return all_zombies
    
    def _estimate_ebs_cost(self, size_gb, volume_type):
        """Estimate monthly cost for EBS volume (rough estimates in USD)"""
        # Rough pricing estimates per GB/month (varies by region)
        pricing = {
            'gp2': 0.10,
            'gp3': 0.08,
            'io1': 0.125,
            'io2': 0.125,
            'st1': 0.045,
            'sc1': 0.025,
            'standard': 0.05
        }
        rate = pricing.get(volume_type, 0.10)  # default to gp2 pricing
        return round(size_gb * rate, 2)
    
    def _estimate_eip_cost(self):
        """Estimate monthly cost for idle Elastic IP"""
        # Idle EIP costs ~$3.65/month
        return 3.65
    
    def display_table(self, zombies):
        """Display zombies in a rich table format"""
        if not zombies:
            self.console.print("🎉 No zombie resources found!")
            return
        
        table = Table(title="🧟 Zombie Resources Found", show_header=True, header_style="bold magenta")
        table.add_column("Resource Type", style="cyan", width=12)
        table.add_column("Resource ID", style="yellow", width=25)
        table.add_column("Region", style="blue", width=12)
        table.add_column("Monthly Cost", style="green", justify="right", width=12)
        table.add_column("Risk Score", width=10)
        table.add_column("AI Reason", style="dim", width=60)
        
        total_cost = 0
        risk_counts = {'Low': 0, 'Medium': 0, 'High': 0, 'Unknown': 0}
        
        for zombie in zombies:
            # Resource type formatting
            resource_type = zombie['resource_type'].replace('_', ' ').title()
            
            # Cost formatting
            cost = zombie.get('cost_estimate', 0)
            total_cost += cost
            cost_str = f"${cost:.2f}"
            
            # Risk score with color
            ai_analysis = zombie.get('ai_analysis', {})
            risk_score = ai_analysis.get('risk_score', 'Unknown')
            risk_counts[risk_score] += 1
            
            risk_color = {
                'Low': 'green',
                'Medium': 'yellow',
                'High': 'red',
                'Unknown': 'dim'
            }.get(risk_score, 'dim')
            
            risk_text = Text(risk_score, style=risk_color)
            
            # AI reason (truncated if too long)
            reason = ai_analysis.get('reason', 'No analysis available')
            if len(reason) > 57:
                reason = reason[:54] + "..."
            
            table.add_row(
                resource_type,
                zombie['resource_id'],
                zombie['region'],
                cost_str,
                risk_text,
                reason
            )
        
        self.console.print(table)
        
        # Summary
        self.console.print(f"\n💰 Total estimated monthly cost: [bold green]${total_cost:.2f}[/bold green]")
        self.console.print(f"🚦 Risk Summary: [green]Low: {risk_counts['Low']}[/green], [yellow]Medium: {risk_counts['Medium']}[/yellow], [red]High: {risk_counts['High']}[/red], [dim]Unknown: {risk_counts['Unknown']}[/dim]")
    
    def generate_markdown_report(self, zombies, filename):
        """Generate a markdown report of zombie resources"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report = f"""# Zombie Hunter Report
Generated on: {timestamp}

## Summary
- **Total Resources Found:** {len(zombies)}
- **Estimated Monthly Cost:** ${sum(z.get('cost_estimate', 0) for z in zombies):.2f}

"""
        
        if zombies:
            # Risk breakdown
            risk_counts = {'Low': 0, 'Medium': 0, 'High': 0, 'Unknown': 0}
            for zombie in zombies:
                risk = zombie.get('ai_analysis', {}).get('risk_score', 'Unknown')
                risk_counts[risk] += 1
            
            report += f"""## Risk Breakdown
- 🟢 **Low Risk:** {risk_counts['Low']} resources
- 🟡 **Medium Risk:** {risk_counts['Medium']} resources  
- 🔴 **High Risk:** {risk_counts['High']} resources
- ⚪ **Unknown Risk:** {risk_counts['Unknown']} resources

## Detailed Resources

| Resource Type | Resource ID | Region | Monthly Cost | Risk | AI Analysis |
|---------------|-------------|---------|--------------|------|-------------|
"""
            
            for zombie in zombies:
                resource_type = zombie['resource_type'].replace('_', ' ').title()
                resource_id = zombie['resource_id']
                region = zombie['region']
                cost = f"${zombie.get('cost_estimate', 0):.2f}"
                
                ai_analysis = zombie.get('ai_analysis', {})
                risk = ai_analysis.get('risk_score', 'Unknown')
                reason = ai_analysis.get('reason', 'No analysis available')
                
                # Risk emoji
                risk_emoji = {'Low': '🟢', 'Medium': '🟡', 'High': '🔴', 'Unknown': '⚪'}.get(risk, '⚪')
                
                report += f"| {resource_type} | `{resource_id}` | {region} | {cost} | {risk_emoji} {risk} | {reason} |\n"
            
            # Recommendations
            report += f"""

## Recommendations

### 🟢 Low Risk Resources ({risk_counts['Low']})
These resources appear safe to delete. Consider removing them to reduce costs.

### 🟡 Medium Risk Resources ({risk_counts['Medium']})  
Review these resources carefully. Check with resource owners before deletion.

### 🔴 High Risk Resources ({risk_counts['High']})
**DO NOT DELETE** these resources without thorough investigation. They may be critical to production systems.

### ⚪ Unknown Risk Resources ({risk_counts['Unknown']})
AI analysis was not available for these resources. Manual review recommended.

---
*Report generated by Zombie Hunter CLI tool*
"""
        else:
            report += "🎉 **No zombie resources found!** Your AWS account is clean.\n"
        
        with open(filename, 'w') as f:
            f.write(report)
        
        self.console.print(f"📄 Report saved to: [bold blue]{filename}[/bold blue]")
    
    def analyze_with_ai(self, zombies):
        """Analyze zombie resources using Amazon Bedrock with fallback models"""
        if not zombies:
            return zombies
        
        # List of models to try in order of preference
        models_to_try = [
            'anthropic.claude-3-haiku-20240307-v1:0',
            'anthropic.claude-3-5-sonnet-20241022-v2:0',
            'anthropic.claude-3-sonnet-20240229-v1:0',
            'anthropic.claude-instant-v1'
        ]
        
        try:
            bedrock = self.session.client('bedrock-runtime', region_name=self.bedrock_region)
            
            # Create analysis prompt
            prompt = self._create_analysis_prompt(zombies)
            
            # Try each model until one works
            for model_id in models_to_try:
                try:
                    self.console.print(f"Trying model: {model_id}")
                    
                    # Call Bedrock
                    response = bedrock.invoke_model(
                        modelId=model_id,
                        body=json.dumps({
                            "anthropic_version": "bedrock-2023-05-31",
                            "max_tokens": 4000,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": prompt
                                }
                            ]
                        })
                    )
                    
                    # Parse response
                    response_body = json.loads(response['body'].read())
                    analysis_text = response_body['content'][0]['text']
                    
                    # Parse AI analysis and merge with original data
                    self.console.print(f"✅ Successfully used model: {model_id}")
                    return self._merge_analysis(zombies, analysis_text)
                    
                except ClientError as e:
                    error_code = e.response['Error']['Code']
                    if error_code in ['ResourceNotFoundException', 'ValidationException', 'AccessDeniedException']:
                        self.console.print(f"❌ Model {model_id} not available: {error_code}")
                        continue  # Try next model
                    else:
                        raise  # Re-raise unexpected errors
            
            # If we get here, no models worked
            raise Exception("No Bedrock models are available for your account")
            
        except Exception as e:
            self.console.print(f"AI analysis failed: {e}")
            # Return original data without analysis
            for zombie in zombies:
                zombie['ai_analysis'] = {
                    'risk_score': 'Unknown',
                    'reason': 'AI analysis unavailable - check Bedrock model access'
                }
            return zombies
    
    def _create_analysis_prompt(self, zombies):
        """Create prompt for AI analysis"""
        resources_text = ""
        for i, zombie in enumerate(zombies):
            tags_str = ", ".join([f"{k}={v}" for k, v in zombie.get('tags', {}).items()])
            if not tags_str:
                tags_str = "No tags"
            
            resources_text += f"{i+1}. {zombie['resource_type']} {zombie['resource_id']} in {zombie['region']}\n"
            resources_text += f"   Tags: {tags_str}\n"
            if 'size' in zombie:
                resources_text += f"   Size: {zombie['size']}GB\n"
            if 'public_ip' in zombie:
                resources_text += f"   IP: {zombie['public_ip']}\n"
            resources_text += "\n"
        
        return f"""Analyze these AWS resources to determine if they're safe to delete. For each resource, provide a risk score (Low/Medium/High) and a one-sentence reason.

Consider these factors:
- Tags indicating purpose, environment, or ownership
- Resource names suggesting production use
- Size/cost implications
- Common patterns that suggest active use

Resources to analyze:
{resources_text}

Respond in this exact JSON format:
{{
  "analyses": [
    {{
      "resource_number": 1,
      "risk_score": "Low|Medium|High",
      "reason": "One sentence explanation"
    }}
  ]
}}"""
    
    def _merge_analysis(self, zombies, analysis_text):
        """Merge AI analysis with zombie data"""
        try:
            # Extract JSON from AI response
            start_idx = analysis_text.find('{')
            end_idx = analysis_text.rfind('}') + 1
            if start_idx == -1 or end_idx == 0:
                raise ValueError("No JSON found in response")
            
            json_str = analysis_text[start_idx:end_idx]
            analysis_data = json.loads(json_str)
            
            # Merge analysis with zombie data
            for analysis in analysis_data.get('analyses', []):
                resource_idx = analysis['resource_number'] - 1
                if 0 <= resource_idx < len(zombies):
                    zombies[resource_idx]['ai_analysis'] = {
                        'risk_score': analysis['risk_score'],
                        'reason': analysis['reason']
                    }
            
            # Add default analysis for any missing resources
            for i, zombie in enumerate(zombies):
                if 'ai_analysis' not in zombie:
                    zombie['ai_analysis'] = {
                        'risk_score': 'Unknown',
                        'reason': 'Analysis not available for this resource'
                    }
            
            return zombies
            
        except Exception as e:
            click.echo(f"Error parsing AI analysis: {e}", err=True)
            # Add default analysis
            for zombie in zombies:
                zombie['ai_analysis'] = {
                    'risk_score': 'Unknown',
                    'reason': 'Failed to parse AI analysis'
                }
            return zombies


@click.command()
@click.option('--regions', '-r', multiple=True, help='Specific regions to scan (default: all regions)')
@click.option('--output', '-o', type=click.File('w'), help='Output JSON file (default: display table)')
@click.option('--pretty', is_flag=True, help='Pretty print JSON output')
@click.option('--analyze', is_flag=True, help='Use AI to analyze deletion risk for each resource')
@click.option('--bedrock-region', default='us-east-1', help='AWS region for Bedrock service (default: us-east-1, try us-west-2 if access denied)')
@click.option('--report', type=str, help='Generate markdown report (provide filename, e.g., report.md)')
@click.option('--test-bedrock', is_flag=True, help='Test Bedrock access without scanning resources')
def main(regions, output, pretty, analyze, bedrock_region, report, test_bedrock):
    """Zombie Hunter - Find unattached EBS volumes and idle Elastic IPs"""
    
    try:
        hunter = ZombieHunter(bedrock_region=bedrock_region)
        
        # Test Bedrock access if requested
        if test_bedrock:
            hunter.console.print("🧪 [bold]Testing Bedrock Access...[/bold]")
            test_zombies = [{
                'resource_type': 'ebs_volume',
                'resource_id': 'vol-test123',
                'region': 'us-east-1',
                'tags': {'Name': 'test-volume', 'Environment': 'test'},
                'cost_estimate': 1.0
            }]
            hunter.analyze_with_ai(test_zombies)
            return
        
        # Use specified regions or all regions
        scan_regions = list(regions) if regions else None
        
        hunter.console.print("🧟 [bold]Starting Zombie Hunt...[/bold]")
        zombies = hunter.hunt_zombies(scan_regions)
        
        # AI Analysis if requested
        if analyze:
            if zombies:
                hunter.console.print("🤖 [bold]Running AI analysis...[/bold]")
                zombies = hunter.analyze_with_ai(zombies)
                
                # Check if AI analysis actually worked
                ai_worked = any(z.get('ai_analysis', {}).get('risk_score') != 'Unknown' for z in zombies)
                if not ai_worked:
                    hunter.console.print("\n💡 [yellow]AI analysis unavailable. Here's manual guidance:[/yellow]")
                    hunter.console.print("   • Resources with 'test', 'dev', 'temp' tags are usually [green]Low Risk[/green]")
                    hunter.console.print("   • Resources with 'prod', 'production' tags are [red]High Risk[/red]")
                    hunter.console.print("   • Resources without tags need manual review ([yellow]Medium Risk[/yellow])")
                    hunter.console.print("   • Small volumes (<10GB) are often safe to delete")
                    hunter.console.print("   • Check resource creation date - old unused resources are good candidates")
            else:
                hunter.console.print("No zombies found to analyze")
        
        # Output handling
        if output:
            # JSON output to file
            if pretty:
                json.dump(zombies, output, indent=2, default=str)
            else:
                json.dump(zombies, output, default=str)
            hunter.console.print(f"📄 JSON output saved to file")
        else:
            # Rich table display (default)
            hunter.display_table(zombies)
        
        # Generate markdown report if requested
        if report:
            hunter.generate_markdown_report(zombies, report)
        
    except NoCredentialsError:
        console = Console()
        console.print("❌ [red]AWS credentials not found. Please configure your credentials.[/red]")
        exit(1)
    except Exception as e:
        console = Console()
        console.print(f"❌ [red]Error: {e}[/red]")
        exit(1)


if __name__ == '__main__':
    main()