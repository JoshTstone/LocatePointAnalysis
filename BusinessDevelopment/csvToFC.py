import arcpy
import os

# PART 1: Create layer from CSV
# Set workspace environment for the new layer
csv_path = r"\\gisappser2\Engineering_GIS\JoshTouchstone\Exports\BusinessDevelopment"
workspace = r"\\gisappser2\Engineering_GIS\JoshTouchstone\Exports\BusinessDevelopment\UpdateSEBusinessDevFC.gdb"

# Input CSV file
csv_file = "UpdateSEBusinessDevFC.csv"
csv = os.path.join(csv_path, csv_file)

# Set the workspace
arcpy.env.workspace = workspace

# Save current overwrite setting (error w/ overwriting Table for CSV, this is to ensure)
current_overwrite_setting = arcpy.env.overwriteOutput
arcpy.env.overwriteOutput = True
# Convert CSV to table in geodatabase
csv_table = arcpy.conversion.TableToTable(csv, workspace, "UpdateSEBusinessDevFC_Table")

# Create a spatial reference object for WGS 1984 (auxiliary sphere)
spatial_reference = arcpy.SpatialReference(4326)  # WKID for WGS 1984

# Make XY Event Layer
new_layer = "Update_BusinessDev_Layer"

arcpy.env.workspace = r"\\gisappser2\Engineering_GIS\JoshTouchstone\Exports\BusinessDevelopment\UpdateSEBusinessDevFC.gdb"

try:
    # Create the feature layer from CSV
    arcpy.management.XYTableToPoint(
        in_table=csv_table,
        out_feature_class=new_layer,
        x_field="Longitude",
        y_field="Latitude",
        coordinate_system=spatial_reference
    )

    print(f"Successfully created feature layer: {new_layer}")

    # PART 2: Compare and Update existing feature class
    # Change workspace for comparing with existing FC
    arcpy.env.workspace = r"\\stl-pgmm-190\GisServerManager\Data\SoutheastBusinessDevelopment\SoutheastBusinessDevelopment.gdb"
    existing_fc = "Southeast_BusinessDevelopment_Projects"

    # Define field mappings (new_layer_field: existing_fc_field)
    field_mappings = {
        "PROJECT_NAME": "PROJECT_NAME",
        "Channel": "Channel",
        "Business_Unit": "Business_Unit",
        "Rep": "Rep",
        "Salesforce_Opp_ID": "Salesforce_Opp_ID",
        "Latitude": "Latitude",
        "Longitude": "Longitude",
        "Street_Address": "Street_Address",
        "City": "City",
        "State": "State",
        "Zip_Code": "Zip_Code",
        "Status": "Status",
        "Lot_Count": "Lot_Count",
        "Note": "Note"
    }

    # Fields to ignore in comparison and updates
    ignore_fields = ["GlobalID", "CREATED_USER", "CREATED_DATE", "MODIFIED_BY", "MODIFIED_DATE", "OBJECTID", "Shape"]

    # Create lists of fields to use in cursors
    new_layer_fields = list(field_mappings.keys())
    existing_fc_fields = [field for field in field_mappings.values() if field not in ignore_fields]

    # Read new layer data
    new_layer_path = r"\\gisappser2\Engineering_GIS\JoshTouchstone\Exports\BusinessDevelopment\UpdateSEBusinessDevFC.gdb\Update_BusinessDev_Layer"
    new_data = {}
    with arcpy.da.SearchCursor(new_layer_path, new_layer_fields) as cursor:
        for row in cursor:
            project_name = row[0]  # PROJECT_NAME is our key field
            new_data[project_name] = dict(zip(new_layer_fields, row))
            print(f"New data for {project_name}: {new_data[project_name]}")

    print("\nStarting update process...")

    # Start an edit session
    edit = arcpy.da.Editor(arcpy.env.workspace)
    edit.startEditing(False, True)
    edit.startOperation()

    try:
        # First, identify existing records and their statuses
        existing_records = {}
        records_to_delete = []
        records_to_append = list(new_data.keys())  # Start with all new records

        with arcpy.da.SearchCursor(existing_fc, existing_fc_fields) as cursor:
            for row in cursor:
                project_name = row[0]
                existing_records[project_name] = dict(zip(existing_fc_fields, row))

                if project_name in new_data:
                    # Remove from append list since it exists
                    records_to_append.remove(project_name)

                    # Check if lat/long changed
                    old_lat = row[existing_fc_fields.index("Latitude")]
                    old_long = row[existing_fc_fields.index("Longitude")]
                    new_lat = new_data[project_name]["Latitude"]
                    new_long = new_data[project_name]["Longitude"]

                    if old_lat != new_lat or old_long != new_long:
                        records_to_delete.append(project_name)
                        print(f"\nLocation change detected for {project_name}:")
                        print(f"  Old Location: Lat {old_lat}, Long {old_long}")
                        print(f"  New Location: Lat {new_lat}, Long {new_long}")
                        print("  Record will be deleted and re-appended")

        # Delete records where location changed
        if records_to_delete:
            print("\nDeleting records with changed locations...")
            with arcpy.da.UpdateCursor(existing_fc, ["PROJECT_NAME"]) as cursor:
                for row in cursor:
                    if row[0] in records_to_delete:
                        cursor.deleteRow()
                        print(f"Deleted record: {row[0]}")

        # Append records (both new and location-changed)
        records_to_append.extend(records_to_delete)  # Add location-changed records to append list

        if records_to_append:
            print("\nAppending new records and location-changed records...")
            # Create temporary feature layer for appending
            temp_layer = "temp_append_layer"
            arcpy.management.MakeFeatureLayer(new_layer_path, temp_layer)

            # Create where clause for selection
            quoted_names = ["'" + name.replace("'", "''") + "'" for name in records_to_append]
            where_clause = "PROJECT_NAME IN (" + ",".join(quoted_names) + ")"

            # Add selection to temp layer for records to append
            arcpy.management.SelectLayerByAttribute(temp_layer, "NEW_SELECTION", where_clause)

            # Append selected records
            arcpy.management.Append(temp_layer, existing_fc, "NO_TEST")

            print("Appended records:")
            for record in records_to_append:
                print(f"  {record}")

        # Commit the edit operation
        edit.stopOperation()
        edit.stopEditing(True)

        print(f"\nUpdate process complete!")
        print(f"Records deleted due to location change: {len(records_to_delete)}")
        print(f"Total records appended: {len(records_to_append)}")

    except Exception as e:
        # If there's an error, abort the edit operation
        edit.abortOperation()
        edit.stopEditing(False)
        raise e

except arcpy.ExecuteError:
    print(arcpy.GetMessages(2))
    print(arcpy.GetMessages())
except Exception as e:
    print(f"An error occurred: {str(e)}")
