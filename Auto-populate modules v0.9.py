from extras.scripts import Script, ObjectVar, MultiObjectVar, StringVar, BooleanVar
from dcim.models import Device, DeviceType, ModuleBay, Module, ModuleType, ModuleBayTemplate
from django.core.exceptions import ObjectDoesNotExist
from django.db.utils import IntegrityError
import json


class DynamicModuleCreation(Script):
    """
    Dynamically create and install modules for devices with varying module bay configurations.
    Supports different bay numbers and quantities per device type.
    """
    
    class Meta:
        name = "Dynamic Module Creation"
        description = "Auto-populate modules based on device type with flexible bay configuration"
        commit_default = True
    
    device_type = ObjectVar(
        model=DeviceType,
        required=True,
        description="Select the device type/template",
        label="Device Type/Template"
    )
    
    devices = MultiObjectVar(
        model=Device,
        required=True,
        description="Select one or more devices to populate modules",
        label="Devices",
        query_params={'device_type_id': '$device_type'}
    )
    
    module_config = StringVar(
        required=True,
        description='Map bay names to module types. Example: {"PWR1": "PDC-350WA", "PWR2": "PDC-350WA"}',
        label="Module Configuration (JSON - by Bay Name)",
        default='{"PWR1": "", "PWR2": ""}'
    )
    
    replicate_components = BooleanVar(
        default=True,
        label="Replicate Components",
        description="Create interfaces/ports from module type template (recommended)"
    )
    
    adopt_components = BooleanVar(
        default=False,
        label="Adopt Components",
        description="Adopt existing unassigned components on the device"
    )
    
    module_description = StringVar(
        required=False,
        label="Module Description (optional)",
        description="Add a description to all created modules"
    )
    
    def run(self, data, commit):
        device_type = data['device_type']
        devices = data['devices']
        module_config_str = data['module_config']
        replicate = data.get('replicate_components', True)
        adopt = data.get('adopt_components', False)
        description = data.get('module_description', '') or ''
        if description:
            description = description.strip()
        
        # Parse module configuration
        try:
            module_config = json.loads(module_config_str)
        except json.JSONDecodeError:
            self.log_failure("Invalid JSON format in module configuration")
            return "Error: Invalid JSON format"
        
        # Get module bay templates
        template_bays = ModuleBayTemplate.objects.filter(device_type=device_type).order_by('position')
        
        if not template_bays.exists():
            self.log_warning(f"No module bays found for device type: {device_type.model}")
            return "No module bays in template"
        
        self.log_info(f"{'='*70}")
        self.log_info(f"DEVICE TYPE: {device_type.manufacturer} {device_type.model}")
        self.log_info(f"{'='*70}")
        self.log_info(f"Available Module Bays: {template_bays.count()}")
        
        for idx, bay in enumerate(template_bays, 1):
            pos_str = f"Position {bay.position}" if bay.position else "No Position"
            self.log_info(f"  #{idx}. {bay.name} ({pos_str})")
        
        # Display configuration
        self.log_info(f"\n{'='*70}")
        self.log_info("CONFIGURATION")
        self.log_info(f"{'='*70}")
        self.log_info(f"Replicate Components: {replicate}")
        self.log_info(f"Adopt Components: {adopt}")
        if description:
            self.log_info(f"Description: {description}")
        
        self.log_info(f"\nMODULE MAPPING:")
        
        # Pre-fetch and validate module types
        module_types_cache = {}
        for bay_name, module_model in module_config.items():
            if module_model:
                try:
                    module_type = ModuleType.objects.get(model=module_model)
                    module_types_cache[bay_name] = module_type
                    self.log_info(f"  {bay_name} → {module_type.manufacturer} {module_type.model}")
                except ObjectDoesNotExist:
                    self.log_failure(f"Module type '{module_model}' not found in NetBox")
                    return f"Error: Module type '{module_model}' does not exist"
        
        if not module_types_cache:
            self.log_warning("No modules configured")
            return "Error: No modules configured"
        
        # Process each device
        created_count = 0
        skipped_count = 0
        error_count = 0
        warning_count = 0
        results = []
        
        self.log_info(f"\n{'='*70}")
        self.log_info("PROCESSING DEVICES")
        self.log_info(f"{'='*70}")
        
        for device in devices:
            self.log_info(f"\n▼ {device.name}")
            
            device_bays = ModuleBay.objects.filter(device=device).order_by('position')
            
            if not device_bays.exists():
                self.log_warning(f"  No module bays found")
                error_count += 1
                continue
            
            # Process each bay
            for idx, bay in enumerate(device_bays, 1):
                bay_name = bay.name
                pos_str = str(bay.position) if bay.position else "N/A"
                
                # Check if this bay has a configured module
                if bay_name not in module_config or not module_config[bay_name]:
                    self.log_info(f"  #{idx} {bay_name}: Skipped (not configured)")
                    results.append({
                        'device': device.name,
                        'bay': bay_name,
                        'position': pos_str,
                        'status': 'Skipped',
                        'module': 'Not configured',
                        'warning': ''
                    })
                    skipped_count += 1
                    continue
                
                # Check if bay already occupied
                existing_module = Module.objects.filter(device=device, module_bay=bay).first()
                if existing_module:
                    self.log_warning(f"  #{idx} {bay_name}: Already occupied ({existing_module.module_type.model})")
                    results.append({
                        'device': device.name,
                        'bay': bay_name,
                        'position': pos_str,
                        'status': 'Already Occupied',
                        'module': existing_module.module_type.model,
                        'warning': ''
                    })
                    skipped_count += 1
                    continue  # Skip to next bay, don't try to save
                
                # Get module type
                module_type = module_types_cache.get(bay_name)
                if not module_type:
                    self.log_failure(f"  #{idx} {bay_name}: Module type not in cache")
                    error_count += 1
                    continue
                
                # Create the module
                try:
                    module = Module(
                        device=device,
                        module_bay=bay,
                        module_type=module_type,
                        status='active'
                    )

                    if description:
                        module.description = description

                    # Save with component handling
                    # Note: replicate_components and adopt_components are NetBox 3.5+ features
                    try:
                        module.save(
                            replicate_components=replicate,
                            adopt_components=adopt
                        )
                    except TypeError:
                        # Fallback for older NetBox versions that don't support these parameters
                        self.log_warning(
                            f"  #{idx} {bay_name}: Component replication not supported in this NetBox version"
                        )
                        module.save()

                except IntegrityError as ie:
                    # Handle duplicate component errors
                    error_msg = str(ie)

                    if 'duplicate key' in error_msg.lower():
                        # Extract component name from error
                        warning_msg = "Duplicate component conflict"
                        if 'powerport' in error_msg.lower():
                            warning_msg = "Power port name conflict"
                        elif 'interface' in error_msg.lower():
                            warning_msg = "Interface name conflict"
                        elif 'consoleport' in error_msg.lower():
                            warning_msg = "Console port name conflict"

                        self.log_warning(
                            f"  #{idx} {bay_name}: ⚠ Skipped - {warning_msg}\n"
                            f"      Component already exists on device. Please rename or remove existing component."
                        )

                        results.append({
                            'device': device.name,
                            'bay': bay_name,
                            'position': pos_str,
                            'status': 'Warning',
                            'module': module_type.model,
                            'warning': warning_msg
                        })
                        warning_count += 1
                        skipped_count += 1
                        continue
                    else:
                        raise  # Re-raise if not a duplicate error

                except Exception as e:
                    self.log_failure(f"  #{idx} {bay_name}: ✗ Failed - {str(e)}")
                    results.append({
                        'device': device.name,
                        'bay': bay_name,
                        'position': pos_str,
                        'status': 'Error',
                        'module': module_type.model,
                        'warning': str(e)
                    })
                    error_count += 1

                else:
                    # Success path (no IntegrityError)
                    self.log_success(f"  #{idx} {bay_name}: ✓ Installed {module_type.model}")

                    results.append({
                        'device': device.name,
                        'bay': bay_name,
                        'position': pos_str,
                        'status': 'Created',
                        'module': f"{module_type.manufacturer} {module_type.model}",
                        'warning': ''
                    })
                    created_count += 1
        
        # Generate output report
        output = self._generate_report(
            device_type, devices, results, 
            created_count, skipped_count, error_count, warning_count
        )
        
        return output
    
    def _generate_report(self, device_type, devices, results, created, skipped, errors, warnings):
        """Generate formatted output report"""
        output = []
        
        output.append("=" * 70)
        output.append("INSTALLATION SUMMARY")
        output.append("=" * 70)
        output.append(f"Device Type: {device_type.manufacturer} {device_type.model}")
        output.append(f"Devices Processed: {len(devices)}")
        output.append(f"\nResults:")
        output.append(f"  ✓ Created: {created}")
        output.append(f"  ○ Skipped: {skipped}")
        if warnings > 0:
            output.append(f"  ⚠ Warnings: {warnings}")
        if errors > 0:
            output.append(f"  ✗ Errors: {errors}")
        
        # Breakdown by status
        output.append(f"\n{'=' * 70}")
        output.append("DETAILED BREAKDOWN")
        output.append("=" * 70)
        
        for status in ['Created', 'Warning', 'Already Occupied', 'Skipped', 'Error']:
            status_results = [r for r in results if r['status'] == status]
            if status_results:
                icons = {
                    'Created': '✓', 
                    'Warning': '⚠', 
                    'Already Occupied': '●', 
                    'Skipped': '○', 
                    'Error': '✗'
                }
                output.append(f"\n{icons[status]} {status.upper()} ({len(status_results)}):")
                
                current_device = None
                for result in status_results:
                    if current_device != result['device']:
                        current_device = result['device']
                        output.append(f"  {current_device}:")
                    
                    line = f"    • {result['bay']} (Pos {result['position']}): {result['module']}"
                    if result.get('warning'):
                        line += f" - {result['warning']}"
                    output.append(line)
        
        # Tabular report
        if warnings > 0:
            output.append(f"\n{'=' * 70}")
            output.append("WARNINGS - ACTION REQUIRED")
            output.append("=" * 70)
            output.append("The following modules could not be installed due to duplicate components.")
            output.append("To resolve:")
            output.append("  1. Navigate to the device in NetBox")
            output.append("  2. Find and rename/delete conflicting components")
            output.append("  3. Re-run this script for affected devices")
            
            warning_results = [r for r in results if r['status'] == 'Warning']
            for result in warning_results:
                output.append(f"  • {result['device']} - {result['bay']}: {result['warning']}")
        
        # Table view
        output.append(f"\n{'=' * 70}")
        output.append("TABULAR REPORT")
        output.append("=" * 70)
        output.append(f"{'Device':<25} {'Bay':<12} {'Pos':<6} {'Status':<18} {'Module'}")
        output.append("-" * 70)
        
        for result in results:
            output.append(
                f"{result['device']:<25} "
                f"{result['bay']:<12} "
                f"{result['position']:<6} "
                f"{result['status']:<18} "
                f"{result['module']}"
            )
        
        output.append("\n" + "=" * 70)
        summary = f"FINAL: {created} created | {skipped} skipped"
        if warnings > 0:
            summary += f" | {warnings} warnings"
        if errors > 0:
            summary += f" | {errors} errors"
        output.append(summary)
        output.append("=" * 70)
        
        return "\n".join(output)


class SimplifiedModuleInstaller(Script):
    """
    Simplified module installation - select bay names and modules directly
    """
    
    class Meta:
        name = "Simplified Module Installer"
        description = "Easy module installation by bay name selection"
        commit_default = True
    
    device_type = ObjectVar(
        model=DeviceType,
        required=True,
        label="1. Device Type"
    )
    
    devices = MultiObjectVar(
        model=Device,
        required=True,
        label="2. Select Devices",
        query_params={'device_type_id': '$device_type'}
    )
    
    bay_name_1 = StringVar(
        required=False,
        label="3a. Bay Name #1 (e.g., PWR1)",
        description="Enter exact bay name from device type"
    )
    
    module_type_1 = ObjectVar(
        model=ModuleType,
        required=False,
        label="3b. Module for Bay #1"
    )
    
    bay_name_2 = StringVar(
        required=False,
        label="4a. Bay Name #2 (e.g., PWR2)"
    )
    
    module_type_2 = ObjectVar(
        model=ModuleType,
        required=False,
        label="4b. Module for Bay #2"
    )
    
    bay_name_3 = StringVar(
        required=False,
        label="5a. Bay Name #3"
    )
    
    module_type_3 = ObjectVar(
        model=ModuleType,
        required=False,
        label="5b. Module for Bay #3"
    )
    
    bay_name_4 = StringVar(
        required=False,
        label="6a. Bay Name #4"
    )
    
    module_type_4 = ObjectVar(
        model=ModuleType,
        required=False,
        label="6b. Module for Bay #4"
    )
    
    replicate_components = BooleanVar(
        default=True,
        label="Replicate Components",
        description="Create interfaces/ports from module template"
    )
    
    adopt_components = BooleanVar(
        default=False,
        label="Adopt Components",
        description="Adopt existing unassigned components"
    )
    
    module_description = StringVar(
        required=False,
        label="Module Description (optional)"
    )
    
    def run(self, data, commit):
        device_type = data['device_type']
        devices = data['devices']
        replicate = data.get('replicate_components', True)
        adopt = data.get('adopt_components', False)
        description = data.get('module_description', '') or ''
        if description:
            description = description.strip()
        
        # Build bay configuration
        bay_config = {}
        for i in range(1, 5):
            bay_name = data.get(f'bay_name_{i}')
            module_type = data.get(f'module_type_{i}')
            if bay_name and module_type:
                bay_config[bay_name.strip()] = module_type
        
        if not bay_config:
            return "Error: No bay/module pairs configured"
        
        # Show configuration
        template_bays = ModuleBayTemplate.objects.filter(device_type=device_type)
        self.log_info(f"Available bays in {device_type.model}:")
        for bay in template_bays:
            self.log_info(f"  - {bay.name}")
        
        self.log_info(f"\nModule Configuration:")
        for bay_name, mod_type in bay_config.items():
            self.log_info(f"  {bay_name} → {mod_type.model}")
        
        self.log_info(f"\nReplicate Components: {replicate}")
        self.log_info(f"Adopt Components: {adopt}")
        
        # Install modules
        created = 0
        skipped = 0
        warnings = 0
        results = []
        
        for device in devices:
            self.log_info(f"\n{device.name}:")
            device_bays = ModuleBay.objects.filter(device=device)
            
            for bay in device_bays:
                if bay.name in bay_config:
                    module_type = bay_config[bay.name]
                    
                    # Check if module already exists
                    existing = Module.objects.filter(device=device, module_bay=bay).first()
                    if existing:
                        self.log_warning(f"  {bay.name}: Already occupied")
                        skipped += 1
                        continue  # Skip to next bay
                    
                    # Create new module
                    try:
                        module = Module(
                            device=device,
                            module_bay=bay,
                            module_type=module_type,
                            status='active'
                        )
                        
                        if description:
                            module.description = description
                        
                        # Save with component replication options
                        try:
                            module.save(
                                replicate_components=replicate,
                                adopt_components=adopt
                            )
                        except TypeError:
                            # Fallback for NetBox versions that don't support these parameters
                            module.save()
                        
                        self.log_success(f"  ✓ {bay.name}: {module_type.model}")
                        created += 1
                        results.append(f"{device.name} | {bay.name} | {module_type.model}")
                        
                    except IntegrityError as ie:
                        if 'duplicate key' in str(ie).lower():
                            self.log_warning(f"  ⚠ {bay.name}: Component conflict - skipped")
                            warnings += 1
                            skipped += 1
                        else:
                            raise
        
        output = [
            "=" * 60,
            "INSTALLATION COMPLETE",
            "=" * 60,
            f"Created: {created}",
            f"Skipped: {skipped}",
        ]
        
        if warnings > 0:
            output.append(f"Warnings: {warnings} (duplicate components)")
        
        output.extend(["", "Details:", *results, "=" * 60])
        
        return "\n".join(output)