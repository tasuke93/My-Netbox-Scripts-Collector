from extras.scripts import Script, ObjectVar, ChoiceVar, IntegerVar, MultiObjectVar
from dcim.models import Device, RearPort, Cable
from dcim.choices import CableTypeChoices, CableLengthUnitChoices
from tenancy.models import Tenant, TenantGroup
from extras.models import Tag


class LinkRearPorts(Script):
    class Meta:
        name = "Link Rear Ports (Rear-to-Rear)"
        description = "Automatically create cables between rear ports of two devices (e.g., patch panels)"
        commit_default = False

    device_a = ObjectVar(
        model=Device,
        description="First device (e.g., Patch Panel A)"
    )
    
    device_b = ObjectVar(
        model=Device,
        description="Second device (e.g., Patch Panel B)"
    )
    
    cable_type = ChoiceVar(
        choices=CableTypeChoices,
        required=False,
        description="Cable type (optional)"
    )
    
    cable_length = IntegerVar(
        required=False,
        label="Cable length",
        description="Cable length (optional)"
    )
    
    cable_length_unit = ChoiceVar(
        choices=CableLengthUnitChoices,
        required=False,
        label="Length unit",
        description="Cable length unit"
    )
    
    tenant_group = ObjectVar(
        model=TenantGroup,
        required=False,
        description="Tenant group (optional)"
    )
    
    tenant = ObjectVar(
        model=Tenant,
        required=False,
        description="Tenant (optional)",
        query_params={
            'group_id': '$tenant_group'
        }
    )
    
    tags = MultiObjectVar(
        model=Tag,
        required=False,
        description="Tags (optional)"
    )
    


    def run(self, data, commit):
        device_a = data['device_a']
        device_b = data['device_b']
        cable_type = data.get('cable_type')
        cable_length = data.get('cable_length')
        cable_length_unit = data.get('cable_length_unit')
        tenant_group = data.get('tenant_group')
        tenant = data.get('tenant')
        tags = data.get('tags', [])
        
        self.log_debug("=" * 60)
        self.log_debug("DEBUG: Starting script execution")
        self.log_debug(f"DEBUG: Device A: {device_a.name} (ID: {device_a.id})")
        self.log_debug(f"DEBUG: Device B: {device_b.name} (ID: {device_b.id})")
        self.log_debug(f"DEBUG: Cable Type: {cable_type}")
        self.log_debug(f"DEBUG: Cable Length: {cable_length}")
        self.log_debug(f"DEBUG: Tenant: {tenant}")
        self.log_debug(f"DEBUG: Tags: {tags}")
        self.log_debug("=" * 60)
        
        self.log_info(f"Linking Device A: {device_a.name} with Device B: {device_b.name}")
        
        # Get rear ports for both devices
        self.log_debug("DEBUG: Fetching rear ports...")
        rear_ports_a = RearPort.objects.filter(device=device_a).order_by('name')
        rear_ports_b = RearPort.objects.filter(device=device_b).order_by('name')
        
        port_count_a = rear_ports_a.count()
        port_count_b = rear_ports_b.count()
        
        self.log_debug(f"DEBUG: Device A rear ports count: {port_count_a}")
        self.log_debug(f"DEBUG: Device B rear ports count: {port_count_b}")
        
        if port_count_a > 0:
            self.log_debug(f"DEBUG: First 3 ports on Device A: {[rp.name for rp in rear_ports_a[:3]]}")
        if port_count_b > 0:
            self.log_debug(f"DEBUG: First 3 ports on Device B: {[rp.name for rp in rear_ports_b[:3]]}")
        
        self.log_info(f"{device_a.name} has {port_count_a} rear ports")
        self.log_info(f"{device_b.name} has {port_count_b} rear ports")
        
        # Validate both devices have rear ports
        if port_count_a == 0:
            self.log_failure(f"{device_a.name} has no rear ports")
            return
        
        if port_count_b == 0:
            self.log_failure(f"{device_b.name} has no rear ports")
            return
        
        # Check if port counts match
        if port_count_a != port_count_b:
            self.log_failure(f"Port count mismatch!")
            self.log_failure(f"  {device_a.name} has {port_count_a} rear ports")
            self.log_failure(f"  {device_b.name} has {port_count_b} rear ports")
            self.log_failure(f"Both devices must have the same number of rear ports")
            return
        
        port_count = port_count_a
        self.log_success(f"✓ Both devices have {port_count} rear ports")
        
        # Check if any ports are already connected
        self.log_debug("DEBUG: Checking for existing cable connections...")
        connected_ports_a = [rp for rp in rear_ports_a if rp.cable]
        connected_ports_b = [rp for rp in rear_ports_b if rp.cable]
        
        self.log_debug(f"DEBUG: Connected ports on Device A: {len(connected_ports_a)}")
        self.log_debug(f"DEBUG: Connected ports on Device B: {len(connected_ports_b)}")
        
        if connected_ports_a:
            self.log_failure(f"{device_a.name} has {len(connected_ports_a)} rear port(s) already connected:")
            for port in connected_ports_a[:5]:  # Show first 5
                self.log_failure(f"  - {port.name} (Cable ID: {port.cable.id if port.cable else 'None'})")
            if len(connected_ports_a) > 5:
                self.log_failure(f"  ... and {len(connected_ports_a) - 5} more")
            return
        
        if connected_ports_b:
            self.log_failure(f"{device_b.name} has {len(connected_ports_b)} rear port(s) already connected:")
            for port in connected_ports_b[:5]:  # Show first 5
                self.log_failure(f"  - {port.name} (Cable ID: {port.cable.id if port.cable else 'None'})")
            if len(connected_ports_b) > 5:
                self.log_failure(f"  ... and {len(connected_ports_b) - 5} more")
            return
        
        self.log_success(f"✓ All rear ports on both devices are available")
        
        # Log cable properties if set
        if cable_type:
            self.log_info(f"Cable type: {cable_type}")
        if cable_length:
            self.log_info(f"Cable length: {cable_length} {cable_length_unit}")
        if tenant:
            self.log_info(f"Tenant: {tenant}")
        if tags:
            self.log_info(f"Tags: {', '.join([tag.name for tag in tags])}")
        
        self.log_info(f"Starting cable creation for {port_count} ports...")
        
        # Create cables
        cables_created = 0
        
        self.log_debug("DEBUG: Starting cable creation loop...")
        
        for i in range(port_count):
            rear_port_a = rear_ports_a[i]
            rear_port_b = rear_ports_b[i]
            
            self.log_debug(f"DEBUG: Processing port pair {i+1}/{port_count}")
            self.log_debug(f"DEBUG:   Port A: {rear_port_a.name} (ID: {rear_port_a.id})")
            self.log_debug(f"DEBUG:   Port B: {rear_port_b.name} (ID: {rear_port_b.id})")
            
            # Auto-generate cable label
            label = f"{device_a.name}:{rear_port_a.name} <-> {device_b.name}:{rear_port_b.name}"
            self.log_debug(f"DEBUG:   Cable label: {label}")
            
            try:
                # Create cable with all properties
                cable = Cable(
                    label=label
                )
                
                self.log_debug(f"DEBUG:   Cable object created in memory")
                
                # Set optional fields only if provided
                if cable_type:
                    cable.type = cable_type
                    self.log_debug(f"DEBUG:   Set cable type: {cable_type}")
                if cable_length:
                    cable.length = cable_length
                    cable.length_unit = cable_length_unit
                    self.log_debug(f"DEBUG:   Set cable length: {cable_length} {cable_length_unit}")
                if tenant:
                    cable.tenant = tenant
                    self.log_debug(f"DEBUG:   Set tenant: {tenant}")
                
                self.log_debug(f"DEBUG:   Saving cable to database...")
                cable.save()
                self.log_debug(f"DEBUG:   Cable saved with ID: {cable.id}")
                
                # Set terminations after save
                self.log_debug(f"DEBUG:   Setting cable terminations...")
                cable.a_terminations = [rear_port_a]
                cable.b_terminations = [rear_port_b]
                cable.save()
                self.log_debug(f"DEBUG:   Terminations set and saved")
                
                # Add tags if provided
                if tags:
                    self.log_debug(f"DEBUG:   Adding tags: {[tag.name for tag in tags]}")
                    cable.tags.set(tags)
                    self.log_debug(f"DEBUG:   Tags added")
                
                self.log_success(f"Created cable: {rear_port_a.name} ({device_a.name}) <-> {rear_port_b.name} ({device_b.name})")
                cables_created += 1
                
            except Exception as e:
                self.log_failure(f"ERROR: Failed to create cable for ports {rear_port_a.name} <-> {rear_port_b.name}")
                self.log_failure(f"ERROR: Exception type: {type(e).__name__}")
                self.log_failure(f"ERROR: Exception message: {str(e)}")
                import traceback
                self.log_failure(f"ERROR: Traceback: {traceback.format_exc()}")
        
        # Summary
        self.log_info("=" * 60)
        self.log_info(f"SUMMARY:")
        self.log_info(f"  Total cables created: {cables_created}")
        self.log_info("=" * 60)
        
        self.log_success(f"Successfully linked all {cables_created} rear ports between {device_a.name} and {device_b.name}")