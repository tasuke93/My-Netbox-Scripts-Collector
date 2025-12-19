"""
NetBox Script: Sync Device Components from Device Type Template
Author: Script Generator
Version: 3.0
Description: Updates device components (interfaces, rear ports, front ports) to match device type template changes
"""

from extras.scripts import Script, ObjectVar, ChoiceVar, BooleanVar, MultiObjectVar
from dcim.models import (
    Device, DeviceType, Interface, InterfaceTemplate,
    RearPort, RearPortTemplate, FrontPort, FrontPortTemplate
)
from django.db.models import Q
import logging
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

class SyncDeviceComponents(Script):
    class Meta:
        name = "Sync Device Components from Template"
        description = "Update device components to match device type template changes"
        commit_default = False
        
    # Script variables
    device_type = ObjectVar(
        model=DeviceType,
        required=False,
        description="Filter devices by device type (optional)",
        label="Device Type"
    )
    
    devices = MultiObjectVar(
        model=Device,
        required=False,
        query_params={
            'device_type_id': '$device_type'
        },
        description="Select specific devices to update (optional, supports multiple selection)",
        label="Devices"
    )
    
    # Component selection
    sync_interfaces = BooleanVar(
        default=True,
        description="Synchronize device interfaces",
        label="Sync Interfaces"
    )
    
    sync_rear_ports = BooleanVar(
        default=False,
        description="Synchronize rear ports",
        label="Sync Rear Ports"
    )
    
    sync_front_ports = BooleanVar(
        default=False,
        description="Synchronize front ports",
        label="Sync Front Ports"
    )
    
    update_mode = ChoiceVar(
        choices=(
            ('replicate', 'Replicate Components - Create new components from template'),
            ('adopt', 'Adopt Components - Update existing components to match template'),
        ),
        default='adopt',
        description="Choose how to handle component updates",
        label="Update Mode"
    )
    
    log_level = ChoiceVar(
        choices=(
            ('DEBUG', 'Debug'),
            ('INFO', 'Info'),
            ('WARNING', 'Warning'),
            ('ERROR', 'Error'),
        ),
        default='INFO',
        description="Minimum log level to display",
        label="Log Level"
    )
    
    def __init__(self):
        super().__init__()
        self.changes_log = []
        self.stats = {
            'devices_processed': 0,
            'interfaces_created': 0,
            'interfaces_updated': 0,
            'interfaces_deleted': 0,
            'rear_ports_created': 0,
            'rear_ports_updated': 0,
            'rear_ports_deleted': 0,
            'front_ports_created': 0,
            'front_ports_updated': 0,
            'front_ports_deleted': 0,
            'errors': 0
        }
    
    def log_change(self, level, device, message, details=None):
        """Log a change with timestamp and level"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            'timestamp': timestamp,
            'level': level,
            'device': str(device) if device else 'N/A',
            'message': message,
            'details': details or {}
        }
        self.changes_log.append(log_entry)
        
        # Also log to NetBox logger
        log_func = getattr(logger, level.lower(), logger.info)
        log_func(f"[{device}] {message}")
    
    def get_log_level_priority(self, level):
        """Return numeric priority for log level"""
        levels = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3}
        return levels.get(level, 0)
    
    def compare_interfaces(self, device, templates):
        """Compare device interfaces with templates and return changes"""
        changes = {
            'to_create': [],
            'to_update': [],
            'to_delete': []
        }
        
        # Get existing interfaces
        existing_interfaces = {
            iface.name: iface 
            for iface in Interface.objects.filter(device=device)
        }
        
        # Get template interfaces
        template_interfaces = {
            tmpl.name: tmpl 
            for tmpl in templates
        }
        
        self.log_change('DEBUG', device, 
                       f"Comparing {len(existing_interfaces)} existing interfaces with {len(template_interfaces)} template interfaces")
        
        # Find interfaces to create (in template but not in device)
        for tmpl_name, tmpl in template_interfaces.items():
            if tmpl_name not in existing_interfaces:
                changes['to_create'].append(tmpl)
                self.log_change('DEBUG', device, 
                              f"Interface to create: {tmpl_name}")
        
        # Find interfaces to update or delete
        for iface_name, iface in existing_interfaces.items():
            if iface_name not in template_interfaces:
                # Interface exists in device but not in template
                changes['to_delete'].append(iface)
                self.log_change('DEBUG', device, 
                              f"Interface to delete: {iface_name}")
            else:
                # Check if interface needs update
                tmpl = template_interfaces[iface_name]
                needs_update = False
                update_fields = {}
                
                if iface.type != tmpl.type:
                    needs_update = True
                    update_fields['type'] = {
                        'old': iface.type,
                        'new': tmpl.type
                    }
                
                if iface.mgmt_only != tmpl.mgmt_only:
                    needs_update = True
                    update_fields['mgmt_only'] = {
                        'old': iface.mgmt_only,
                        'new': tmpl.mgmt_only
                    }
                
                if needs_update:
                    changes['to_update'].append({
                        'component': iface,
                        'template': tmpl,
                        'fields': update_fields
                    })
                    self.log_change('DEBUG', device, 
                                  f"Interface to update: {iface_name}",
                                  details=update_fields)
        
        return changes
    
    def compare_rear_ports(self, device, templates):
        """Compare device rear ports with templates and return changes"""
        changes = {
            'to_create': [],
            'to_update': [],
            'to_delete': []
        }
        
        # Get existing rear ports
        existing_ports = {
            port.name: port 
            for port in RearPort.objects.filter(device=device)
        }
        
        # Get template rear ports
        template_ports = {
            tmpl.name: tmpl 
            for tmpl in templates
        }
        
        self.log_change('DEBUG', device, 
                       f"Comparing {len(existing_ports)} existing rear ports with {len(template_ports)} template rear ports")
        
        # Find rear ports to create
        for tmpl_name, tmpl in template_ports.items():
            if tmpl_name not in existing_ports:
                changes['to_create'].append(tmpl)
                self.log_change('DEBUG', device, 
                              f"Rear port to create: {tmpl_name}")
        
        # Find rear ports to update or delete
        for port_name, port in existing_ports.items():
            if port_name not in template_ports:
                changes['to_delete'].append(port)
                self.log_change('DEBUG', device, 
                              f"Rear port to delete: {port_name}")
            else:
                tmpl = template_ports[port_name]
                needs_update = False
                update_fields = {}
                
                if port.type != tmpl.type:
                    needs_update = True
                    update_fields['type'] = {
                        'old': port.type,
                        'new': tmpl.type
                    }
                
                if port.positions != tmpl.positions:
                    needs_update = True
                    update_fields['positions'] = {
                        'old': port.positions,
                        'new': tmpl.positions
                    }
                
                if needs_update:
                    changes['to_update'].append({
                        'component': port,
                        'template': tmpl,
                        'fields': update_fields
                    })
                    self.log_change('DEBUG', device, 
                                  f"Rear port to update: {port_name}",
                                  details=update_fields)
        
        return changes
    
    def compare_front_ports(self, device, templates):
        """Compare device front ports with templates and return changes"""
        changes = {
            'to_create': [],
            'to_update': [],
            'to_delete': []
        }
        
        # Get existing front ports
        existing_ports = {
            port.name: port 
            for port in FrontPort.objects.filter(device=device)
        }
        
        # Get template front ports
        template_ports = {
            tmpl.name: tmpl 
            for tmpl in templates
        }
        
        self.log_change('DEBUG', device, 
                       f"Comparing {len(existing_ports)} existing front ports with {len(template_ports)} template front ports")
        
        # Find front ports to create
        for tmpl_name, tmpl in template_ports.items():
            if tmpl_name not in existing_ports:
                changes['to_create'].append(tmpl)
                self.log_change('DEBUG', device, 
                              f"Front port to create: {tmpl_name}")
        
        # Find front ports to update or delete
        for port_name, port in existing_ports.items():
            if port_name not in template_ports:
                changes['to_delete'].append(port)
                self.log_change('DEBUG', device, 
                              f"Front port to delete: {port_name}")
            else:
                tmpl = template_ports[port_name]
                needs_update = False
                update_fields = {}
                
                if port.type != tmpl.type:
                    needs_update = True
                    update_fields['type'] = {
                        'old': port.type,
                        'new': tmpl.type
                    }
                
                # Check rear port reference (use rear_port instead of rear_port_template)
                rear_port_changed = False
                if hasattr(tmpl, 'rear_port') and tmpl.rear_port:
                    expected_rear_port_name = tmpl.rear_port.name
                    if not port.rear_port or port.rear_port.name != expected_rear_port_name:
                        rear_port_changed = True
                        update_fields['rear_port'] = {
                            'old': port.rear_port.name if port.rear_port else None,
                            'new': expected_rear_port_name
                        }
                
                if port.rear_port_position != tmpl.rear_port_position:
                    needs_update = True
                    update_fields['rear_port_position'] = {
                        'old': port.rear_port_position,
                        'new': tmpl.rear_port_position
                    }
                
                if needs_update or rear_port_changed:
                    changes['to_update'].append({
                        'component': port,
                        'template': tmpl,
                        'fields': update_fields
                    })
                    self.log_change('DEBUG', device, 
                                  f"Front port to update: {port_name}",
                                  details=update_fields)
        
        return changes
    
    def apply_interface_replicate(self, device, changes, commit):
        """Apply interface changes in replicate mode"""
        created_count = 0
        
        for template in changes['to_create']:
            try:
                if commit:
                    Interface.objects.create(
                        device=device,
                        name=template.name,
                        type=template.type,
                        mgmt_only=template.mgmt_only,
                        description=f"Created from template on {datetime.now().strftime('%Y-%m-%d')}"
                    )
                
                self.log_change('INFO', device, 
                              f"{'Created' if commit else 'Will create'} interface: {template.name}",
                              details={
                                  'type': template.type,
                                  'mgmt_only': template.mgmt_only
                              })
                created_count += 1
                self.stats['interfaces_created'] += 1
                
            except Exception as e:
                self.log_change('ERROR', device, 
                              f"Failed to create interface: {template.name}",
                              details={'error': str(e)})
                self.stats['errors'] += 1
        
        return created_count
    
    def apply_interface_adopt(self, device, changes, commit):
        """Apply interface changes in adopt mode"""
        updated_count = 0
        
        # Update existing interfaces
        for change in changes['to_update']:
            iface = change['component']
            tmpl = change['template']
            fields = change['fields']
            
            try:
                if commit:
                    iface.type = tmpl.type
                    iface.mgmt_only = tmpl.mgmt_only
                    iface.save()
                
                self.log_change('INFO', device, 
                              f"{'Updated' if commit else 'Will update'} interface: {iface.name}",
                              details=fields)
                updated_count += 1
                self.stats['interfaces_updated'] += 1
                
            except Exception as e:
                self.log_change('ERROR', device, 
                              f"Failed to update interface: {iface.name}",
                              details={'error': str(e)})
                self.stats['errors'] += 1
        
        # Create missing interfaces
        created_count = self.apply_interface_replicate(device, changes, commit)
        
        # Delete orphaned interfaces
        deleted_count = 0
        for iface in changes['to_delete']:
            try:
                if commit:
                    iface.delete()
                
                self.log_change('WARNING', device, 
                              f"{'Deleted' if commit else 'Will delete'} orphaned interface: {iface.name}")
                deleted_count += 1
                self.stats['interfaces_deleted'] += 1
                
            except Exception as e:
                self.log_change('ERROR', device, 
                              f"Failed to delete interface: {iface.name}",
                              details={'error': str(e)})
                self.stats['errors'] += 1
        
        return updated_count + created_count + deleted_count
    
    def apply_rear_port_replicate(self, device, changes, commit):
        """Apply rear port changes in replicate mode"""
        created_count = 0
        
        for template in changes['to_create']:
            try:
                if commit:
                    RearPort.objects.create(
                        device=device,
                        name=template.name,
                        type=template.type,
                        positions=template.positions,
                        description=f"Created from template on {datetime.now().strftime('%Y-%m-%d')}"
                    )
                
                self.log_change('INFO', device, 
                              f"{'Created' if commit else 'Will create'} rear port: {template.name}",
                              details={
                                  'type': template.type,
                                  'positions': template.positions
                              })
                created_count += 1
                self.stats['rear_ports_created'] += 1
                
            except Exception as e:
                self.log_change('ERROR', device, 
                              f"Failed to create rear port: {template.name}",
                              details={'error': str(e)})
                self.stats['errors'] += 1
        
        return created_count
    
    def apply_rear_port_adopt(self, device, changes, commit):
        """Apply rear port changes in adopt mode"""
        updated_count = 0
        
        # Update existing rear ports
        for change in changes['to_update']:
            port = change['component']
            tmpl = change['template']
            fields = change['fields']
            
            try:
                if commit:
                    port.type = tmpl.type
                    port.positions = tmpl.positions
                    port.save()
                
                self.log_change('INFO', device, 
                              f"{'Updated' if commit else 'Will update'} rear port: {port.name}",
                              details=fields)
                updated_count += 1
                self.stats['rear_ports_updated'] += 1
                
            except Exception as e:
                self.log_change('ERROR', device, 
                              f"Failed to update rear port: {port.name}",
                              details={'error': str(e)})
                self.stats['errors'] += 1
        
        # Create missing rear ports
        created_count = self.apply_rear_port_replicate(device, changes, commit)
        
        # Delete orphaned rear ports
        deleted_count = 0
        for port in changes['to_delete']:
            try:
                if commit:
                    port.delete()
                
                self.log_change('WARNING', device, 
                              f"{'Deleted' if commit else 'Will delete'} orphaned rear port: {port.name}")
                deleted_count += 1
                self.stats['rear_ports_deleted'] += 1
                
            except Exception as e:
                self.log_change('ERROR', device, 
                              f"Failed to delete rear port: {port.name}",
                              details={'error': str(e)})
                self.stats['errors'] += 1
        
        return updated_count + created_count + deleted_count
    
    def apply_front_port_replicate(self, device, changes, commit):
        """Apply front port changes in replicate mode"""
        created_count = 0
        
        for template in changes['to_create']:
            try:
                # Find the corresponding rear port
                rear_port = None
                if hasattr(template, 'rear_port') and template.rear_port:
                    try:
                        rear_port = RearPort.objects.get(
                            device=device,
                            name=template.rear_port.name
                        )
                    except RearPort.DoesNotExist:
                        self.log_change('WARNING', device, 
                                      f"Rear port '{template.rear_port.name}' not found for front port '{template.name}'")
                
                if commit and rear_port:
                    FrontPort.objects.create(
                        device=device,
                        name=template.name,
                        type=template.type,
                        rear_port=rear_port,
                        rear_port_position=template.rear_port_position,
                        description=f"Created from template on {datetime.now().strftime('%Y-%m-%d')}"
                    )
                    self.log_change('INFO', device, 
                                  f"Created front port: {template.name}",
                                  details={
                                      'type': template.type,
                                      'rear_port': template.rear_port.name if hasattr(template, 'rear_port') and template.rear_port else None,
                                      'rear_port_position': template.rear_port_position
                                  })
                    created_count += 1
                    self.stats['front_ports_created'] += 1
                elif not commit:
                    self.log_change('INFO', device, 
                                  f"Will create front port: {template.name}",
                                  details={
                                      'type': template.type,
                                      'rear_port': template.rear_port.name if hasattr(template, 'rear_port') and template.rear_port else None,
                                      'rear_port_position': template.rear_port_position
                                  })
                    created_count += 1
                    self.stats['front_ports_created'] += 1
                elif not rear_port:
                    self.log_change('ERROR', device, 
                                  f"Cannot create front port '{template.name}' - rear port not found")
                    self.stats['errors'] += 1
                
            except Exception as e:
                self.log_change('ERROR', device, 
                              f"Failed to create front port: {template.name}",
                              details={'error': str(e)})
                self.stats['errors'] += 1
        
        return created_count
    
    def apply_front_port_adopt(self, device, changes, commit):
        """Apply front port changes in adopt mode"""
        updated_count = 0
        
        # Update existing front ports
        for change in changes['to_update']:
            port = change['component']
            tmpl = change['template']
            fields = change['fields']
            
            try:
                if commit:
                    port.type = tmpl.type
                    port.rear_port_position = tmpl.rear_port_position
                    
                    # Update rear port reference if needed
                    if hasattr(tmpl, 'rear_port') and tmpl.rear_port:
                        try:
                            rear_port = RearPort.objects.get(
                                device=device,
                                name=tmpl.rear_port.name
                            )
                            port.rear_port = rear_port
                        except RearPort.DoesNotExist:
                            self.log_change('WARNING', device, 
                                          f"Rear port '{tmpl.rear_port.name}' not found")
                    
                    port.save()
                
                self.log_change('INFO', device, 
                              f"{'Updated' if commit else 'Will update'} front port: {port.name}",
                              details=fields)
                updated_count += 1
                self.stats['front_ports_updated'] += 1
                
            except Exception as e:
                self.log_change('ERROR', device, 
                              f"Failed to update front port: {port.name}",
                              details={'error': str(e)})
                self.stats['errors'] += 1
        
        # Create missing front ports
        created_count = self.apply_front_port_replicate(device, changes, commit)
        
        # Delete orphaned front ports
        deleted_count = 0
        for port in changes['to_delete']:
            try:
                if commit:
                    port.delete()
                
                self.log_change('WARNING', device, 
                              f"{'Deleted' if commit else 'Will delete'} orphaned front port: {port.name}")
                deleted_count += 1
                self.stats['front_ports_deleted'] += 1
                
            except Exception as e:
                self.log_change('ERROR', device, 
                              f"Failed to delete front port: {port.name}",
                              details={'error': str(e)})
                self.stats['errors'] += 1
        
        return updated_count + created_count + deleted_count
    
    def process_device(self, device, data, commit):
        """Process a single device"""
        self.log_change('INFO', device, "Processing device...")
        
        component_count = 0
        
        # Process Interfaces
        if data['sync_interfaces']:
            self.log_change('INFO', device, "Syncing interfaces...")
            templates = InterfaceTemplate.objects.filter(device_type=device.device_type)
            
            if templates.exists():
                changes = self.compare_interfaces(device, templates)
                total_changes = (len(changes['to_create']) + 
                               len(changes['to_update']) + 
                               len(changes['to_delete']))
                
                if total_changes > 0:
                    self.log_change('INFO', device, 
                                  f"Interface changes: {len(changes['to_create'])} to create, "
                                  f"{len(changes['to_update'])} to update, "
                                  f"{len(changes['to_delete'])} to delete")
                    
                    if data['update_mode'] == 'replicate':
                        component_count += self.apply_interface_replicate(device, changes, commit)
                    else:
                        component_count += self.apply_interface_adopt(device, changes, commit)
                else:
                    self.log_change('INFO', device, "Interfaces already match template")
            else:
                self.log_change('WARNING', device, "No interface templates found")
        
        # Process Rear Ports
        if data['sync_rear_ports']:
            self.log_change('INFO', device, "Syncing rear ports...")
            templates = RearPortTemplate.objects.filter(device_type=device.device_type)
            
            if templates.exists():
                changes = self.compare_rear_ports(device, templates)
                total_changes = (len(changes['to_create']) + 
                               len(changes['to_update']) + 
                               len(changes['to_delete']))
                
                if total_changes > 0:
                    self.log_change('INFO', device, 
                                  f"Rear port changes: {len(changes['to_create'])} to create, "
                                  f"{len(changes['to_update'])} to update, "
                                  f"{len(changes['to_delete'])} to delete")
                    
                    if data['update_mode'] == 'replicate':
                        component_count += self.apply_rear_port_replicate(device, changes, commit)
                    else:
                        component_count += self.apply_rear_port_adopt(device, changes, commit)
                else:
                    self.log_change('INFO', device, "Rear ports already match template")
            else:
                self.log_change('WARNING', device, "No rear port templates found")
        
        # Process Front Ports (must be done after rear ports)
        if data['sync_front_ports']:
            self.log_change('INFO', device, "Syncing front ports...")
            templates = FrontPortTemplate.objects.filter(device_type=device.device_type)
            
            if templates.exists():
                changes = self.compare_front_ports(device, templates)
                total_changes = (len(changes['to_create']) + 
                               len(changes['to_update']) + 
                               len(changes['to_delete']))
                
                if total_changes > 0:
                    self.log_change('INFO', device, 
                                  f"Front port changes: {len(changes['to_create'])} to create, "
                                  f"{len(changes['to_update'])} to update, "
                                  f"{len(changes['to_delete'])} to delete")
                    
                    if data['update_mode'] == 'replicate':
                        component_count += self.apply_front_port_replicate(device, changes, commit)
                    else:
                        component_count += self.apply_front_port_adopt(device, changes, commit)
                else:
                    self.log_change('INFO', device, "Front ports already match template")
            else:
                self.log_change('WARNING', device, "No front port templates found")
        
        return component_count
    
    def run(self, data, commit):
        """Main script execution"""
        self.log_change('INFO', None, "=== Script Execution Started ===")
        
        # Check if at least one component type is selected
        if not any([data['sync_interfaces'], data['sync_rear_ports'], data['sync_front_ports']]):
            return "Error: Please select at least one component type to synchronize."
        
        components_to_sync = []
        if data['sync_interfaces']:
            components_to_sync.append('Interfaces')
        if data['sync_rear_ports']:
            components_to_sync.append('Rear Ports')
        if data['sync_front_ports']:
            components_to_sync.append('Front Ports')
        
        self.log_change('INFO', None, 
                       f"Components to sync: {', '.join(components_to_sync)}")
        self.log_change('INFO', None, 
                       f"Mode: {data['update_mode']}, Commit: {commit}, Log Level: {data['log_level']}")
        
        # Determine which devices to process
        if data.get('devices'):
            # Multiple devices selected
            devices = data['devices']
            self.log_change('INFO', None, f"Processing {len(devices)} selected device(s)")
        elif data.get('device_type'):
            # Filter by device type
            devices = Device.objects.filter(device_type=data['device_type'])
            self.log_change('INFO', None, 
                          f"Processing {devices.count()} devices of type: {data['device_type']}")
        else:
            # All devices
            devices = Device.objects.all()
            self.log_change('INFO', None, 
                          f"Processing all {devices.count()} devices")
        
        if not devices or (hasattr(devices, 'count') and devices.count() == 0):
            self.log_change('WARNING', None, "No devices found to process")
            return "No devices found matching the criteria."
        
        # Process each device
        for device in devices:
            try:
                self.stats['devices_processed'] += 1
                self.process_device(device, data, commit)
                
            except Exception as e:
                self.log_change('ERROR', device, 
                              f"Failed to process device: {str(e)}")
                self.stats['errors'] += 1
        
        # Generate output report
        report = self.generate_report(data['log_level'], commit)
        
        self.log_change('INFO', None, "=== Script Execution Completed ===")
        
        return report
    
    def generate_report(self, min_log_level, commit):
        """Generate and display the final report"""
        min_priority = self.get_log_level_priority(min_log_level)
        
        # Header
        output = []
        output.append("=" * 80)
        output.append("DEVICE COMPONENT SYNCHRONIZATION REPORT")
        output.append("=" * 80)
        output.append("")
        
        # Mode indicator
        if commit:
            output.append("✓ CHANGES APPLIED TO DATABASE")
        else:
            output.append("⚠️  DRY RUN MODE - No changes were committed to database")
        output.append("")
        
        # Statistics
        output.append("STATISTICS:")
        output.append(f"  Devices Processed:       {self.stats['devices_processed']}")
        output.append("")
        output.append("  Interfaces:")
        output.append(f"    Created:               {self.stats['interfaces_created']}")
        output.append(f"    Updated:               {self.stats['interfaces_updated']}")
        output.append(f"    Deleted:               {self.stats['interfaces_deleted']}")
        output.append("")
        output.append("  Rear Ports:")
        output.append(f"    Created:               {self.stats['rear_ports_created']}")
        output.append(f"    Updated:               {self.stats['rear_ports_updated']}")
        output.append(f"    Deleted:               {self.stats['rear_ports_deleted']}")
        output.append("")
        output.append("  Front Ports:")
        output.append(f"    Created:               {self.stats['front_ports_created']}")
        output.append(f"    Updated:               {self.stats['front_ports_updated']}")
        output.append(f"    Deleted:               {self.stats['front_ports_deleted']}")
        output.append("")
        output.append(f"  Errors:                  {self.stats['errors']}")
        output.append("")
        output.append("-" * 80)
        output.append("")
        
        # Detailed log
        output.append(f"DETAILED LOG (Level: {min_log_level} and above):")
        output.append("")
        
        for entry in self.changes_log:
            entry_priority = self.get_log_level_priority(entry['level'])
            
            if entry_priority >= min_priority:
                level_icon = {
                    'DEBUG': '🔍',
                    'INFO': 'ℹ️',
                    'WARNING': '⚠️',
                    'ERROR': '❌'
                }.get(entry['level'], '•')
                
                output.append(f"{level_icon} [{entry['timestamp']}] [{entry['level']}] {entry['device']}")
                output.append(f"   {entry['message']}")
                
                if entry['details']:
                    for key, value in entry['details'].items():
                        if isinstance(value, dict):
                            output.append(f"     {key}:")
                            for k, v in value.items():
                                output.append(f"       {k}: {v}")
                        else:
                            output.append(f"     {key}: {value}")
                output.append("")
        
        output.append("=" * 80)
        output.append("END OF REPORT")
        output.append("=" * 80)
        
        # Return the output string
        return "\n".join(output)


# Register the script
script = SyncDeviceComponents