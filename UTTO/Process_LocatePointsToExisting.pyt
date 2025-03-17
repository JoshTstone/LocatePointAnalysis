"""
Locate Points Processing Toolbox
ArcPro Version: 3.1.7
Created: 11/7/2024
Modified: 3/17/2025

This toolbox processes locate points 
and analyzes their proximity to existing underground facilities (lines).

1. Performs proximity analysis between points and lines
2. Categorizes points based on configurable distance thresholds
3. Validates points against criteria including locate score and GPS position values
4. Supports multiple categories with different distance thresholds and validation rules
5. Generates a summary report and updates fields in the input feature class
6. Evaluates if the overall pass rate meets a specified threshold

Usage:
- Add this script as a toolbox in ArcGIS Pro
- Configure categories and validation rules through the tool interface
- Run the tool on your UTTO points and line feature classes

Requirements:
- Input point feature class with OverallScore and Positioning fields
- Input line feature class

Author: Josh Touchstone
"""


import arcpy
from collections import defaultdict
import os

class Toolbox(object):
    def __init__(self):
        self.label = "Process_LocatePointsToExisting"
        self.alias = "locatepointsprocessingtoolbox"
        self.tools = [LocatePointsTool]

class LocatePointsTool(object):
    def __init__(self):
        self.label = "Process UTTO Points"
        self.description = "Process UTTO points with configurable categories and validation rules"
        self.canRunInBackground = False

    def getParameterInfo(self):
        # Define parameter categories
        REQUIRED_CATEGORY = "Required Input Datasets"
        VALIDATION_CATEGORY = "Validation Settings"
        CATEGORY_SETTINGS = "Category Settings"
        OUTPUT_CATEGORY = "Output Settings"
        
        # Required Input Datasets
        utto_points = arcpy.Parameter(
            displayName="Locate Points Feature Class",
            name="utto_points",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input")
        utto_points.category = REQUIRED_CATEGORY
        utto_points.tooltip = "Select the feature class containing UTTO points"

        spire_main = arcpy.Parameter(
            displayName="Line Feature Class",
            name="spire_main",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input")
        spire_main.category = REQUIRED_CATEGORY
        spire_main.tooltip = "Select the Spire Main feature class"

        # Validation Settings
        locate_score = arcpy.Parameter(
            displayName="Minimum Locate Score to Pass",
            name="locate_score",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        locate_score.value = 70
        locate_score.category = VALIDATION_CATEGORY

        gps_values = arcpy.Parameter(
            displayName="Valid GPS Position Values",
            name="gps_values",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        gps_values.value = "R,F"
        gps_values.category = VALIDATION_CATEGORY

        pass_field = arcpy.Parameter(
            displayName="Pass Field (Optional)",
            name="pass_field",
            datatype="Field",
            parameterType="Optional",
            direction="Input")
        pass_field.parameterDependencies = [spire_main.name]
        pass_field.filter.list = ['Text']
        pass_field.category = VALIDATION_CATEGORY
        pass_field.tooltip = "Select the field containing pass/fail values"

        # Number of categories dropdown
        num_categories = arcpy.Parameter(
            displayName="Number of Categories",
            name="num_categories",
            datatype="GPLong",
            parameterType="Required",
            direction="Input")
        num_categories.filter.type = "ValueList"
        num_categories.filter.list = [1, 2, 3, 4, 5]
        num_categories.value = 1  # Default to 1 category
        num_categories.category = CATEGORY_SETTINGS

        # Create parameters for up to 5 categories
        category_params = []
        ordinal = ["1st", "2nd", "3rd", "4th", "5th"]
        for i in range(5):  # 0-4 for categories 1-5
            name_param = arcpy.Parameter(
                displayName=f"{ordinal[i]} Category Name",
                name=f"cat_{i+1}_name",
                datatype="GPString",
                parameterType="Optional",
                direction="Input")
            name_param.category = CATEGORY_SETTINGS

            distance_param = arcpy.Parameter(
                displayName=f"{ordinal[i]} Category Maximum Distance (feet)",
                name=f"cat_{i+1}_distance",
                datatype="GPDouble",
                parameterType="Optional",
                direction="Input")
            # Set default distance only for first category
            if i == 0:
                distance_param.value = 1.0
            distance_param.category = CATEGORY_SETTINGS

            pass_values_param = arcpy.Parameter(
                displayName=f"{ordinal[i]} Category Pass Values (Optional)",
                name=f"cat_{i+1}_pass_values",
                datatype="GPValueTable",
                parameterType="Optional",
                direction="Input")
            pass_values_param.columns = [['GPString', 'Value']]
            pass_values_param.category = CATEGORY_SETTINGS
            pass_values_param.tooltip = "Leave empty to evaluate distance only"

            auth_param = arcpy.Parameter(
                displayName=f"{ordinal[i]} Category Authentication",
                name=f"cat_{i+1}_auth",
                datatype="GPString",
                parameterType="Optional",
                direction="Input")
            auth_param.filter.type = "ValueList"
            auth_param.filter.list = ["Yes", "No"]
            auth_param.value = "No"  # Default to No
            auth_param.category = CATEGORY_SETTINGS

            category_params.extend([name_param, distance_param, pass_values_param, auth_param])

        pass_threshold = arcpy.Parameter(
            displayName="Pass Threshold (%)",
            name="pass_threshold",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input")
        pass_threshold.value = 75
        pass_threshold.category = OUTPUT_CATEGORY

        params = [utto_points, spire_main, locate_score, gps_values, pass_field, num_categories]
        params.extend(category_params)
        params.append(pass_threshold)
        
        return params

    def updateParameters(self, parameters):
        """Update parameters based on user inputs"""
        if not parameters[0].value:  # If no input feature class, return early
            return
            
        # Get the basic parameters
        num_categories = parameters[5].value if parameters[5].value else 0
        
        if not num_categories:
            return
            
        # Update pass field values
        if parameters[4].altered and parameters[4].value and parameters[1].value:  # pass_field and spire_main
            try:
                unique_values = set()
                with arcpy.da.SearchCursor(parameters[1].valueAsText, [parameters[4].valueAsText]) as cursor:
                    for row in cursor:
                        if row[0]:
                            unique_values.add(row[0])
                
                # Update all category pass values parameters
                for i in range(num_categories):
                    base_index = 6 + (i * 4)
                    pass_values_param_index = base_index + 2
                    
                    if pass_values_param_index < len(parameters):
                        if parameters[pass_values_param_index].filters:
                            parameters[pass_values_param_index].filters[0].list = sorted(list(unique_values))
                            
            except Exception as e:
                arcpy.AddMessage(f"Unable to read unique values from field: {str(e)}")

        # Enable/disable category parameters based on selected number of categories
        if num_categories:
            num_cats = int(num_categories)
            for i in range(num_cats):
                base_index = 6 + (i * 4)  # Start of each category's parameters
                
                # Enable all 4 parameters for each category
                for j in range(4):  # name, distance, pass values, auth
                    param_index = base_index + j
                    if param_index < len(parameters):
                        parameters[param_index].enabled = True
                        parameters[param_index].parameterType = "Required"
                    
            # Disable remaining category parameters
            for i in range(num_cats, 5):  # Up to max of 5 categories
                base_index = 6 + (i * 4)
                for j in range(4):  # name, distance, pass values, auth
                    param_index = base_index + j
                    if param_index < len(parameters):
                        parameters[param_index].enabled = False
                        parameters[param_index].parameterType = "Optional"
                        parameters[param_index].value = None

    def execute(self, parameters, messages):
        """Execute the tool."""
        # Unpack parameters
        utto_points = parameters[0].valueAsText
        spire_main = parameters[1].valueAsText
        locate_score = parameters[2].value
        gps_values = parameters[3].valueAsText.split(',')
        pass_field = parameters[4].valueAsText
        num_categories = int(parameters[5].value)
        pass_threshold = parameters[-1].value

        # Process category parameters
        categories = []
        for i in range(num_categories):
            base_index = 6 + (i * 4)
            category = {
                'name': parameters[base_index].valueAsText,
                'distance': parameters[base_index + 1].value,
                'pass_values': [row[0] for row in parameters[base_index + 2].value] if parameters[base_index + 2].value else [],
                'authenticate': parameters[base_index + 3].valueAsText == "Yes"
            }
            categories.append(category)

        try:
            arcpy.AddMessage("Starting UTTO points processing...")
            arcpy.AddMessage(f"Input points: {utto_points}")
            arcpy.AddMessage(f"Input lines: {spire_main}")
            arcpy.AddMessage(f"Minimum locate score: {locate_score}")
            arcpy.AddMessage(f"Valid GPS values: {gps_values}")
            arcpy.AddMessage(f"Number of categories: {num_categories}")
            
            # Print category details
            for cat in categories:
                arcpy.AddMessage(f"\nCategory: {cat['name']}")
                arcpy.AddMessage(f"- Maximum distance: {cat['distance']} feet")
                arcpy.AddMessage(f"- Pass values: {cat['pass_values'] if cat['pass_values'] else 'None (distance only)'}")
                arcpy.AddMessage(f"- Authentication: {'Yes' if cat['authenticate'] else 'No'}")
            
            # Add required fields if they don't exist
            arcpy.AddMessage("\nChecking and adding required fields...")
            
            required_fields = {
                "PROXIMITY_TO_FACILITIES": "DOUBLE",
                "PROXIMITY_RANK": "TEXT",
                "AUTHENTICATED": "TEXT"
            }
            
            existing_fields = [f.name for f in arcpy.ListFields(utto_points)]
            
            for field_name, field_type in required_fields.items():
                if field_name not in existing_fields:
                    arcpy.AddMessage(f"Adding field: {field_name}")
                    arcpy.AddField_management(utto_points, field_name, field_type)
            
            # Perform Near analysis directly on the points
            arcpy.AddMessage("\nPerforming Near analysis...")
            arcpy.analysis.Near(utto_points, spire_main)
            
            # Count total input points
            total_points = int(arcpy.GetCount_management(utto_points)[0])
            arcpy.AddMessage(f"\nTotal input points: {total_points}")
            
            # Initialize results dictionary and counter
            results = defaultdict(int)
            processed_points = 0
            
            # Process points
            point_fields = ['OID@', 'NEAR_DIST', 'PROXIMITY_TO_FACILITIES', 'PROXIMITY_RANK', 'AUTHENTICATED', 
                          'OverallSco', 'Positionin', 'NEAR_FID']
            
            with arcpy.da.UpdateCursor(utto_points, point_fields) as point_cursor:
                for point_row in point_cursor:
                    point_id = point_row[0]
                    near_dist = point_row[1]
                    overall_score = point_row[5]  # OverallSco field
                    position_value = point_row[6]  # Positionin field
                    near_fid = point_row[7]  # NEAR_FID for checking pass values
                    
                    # Convert distance from meters to feet
                    if near_dist is not None:
                        distance_feet = near_dist * 3.28084  # Convert meters to feet
                        processed_points += 1
                        
                        # Validate against user-defined parameters
                        locate_pass = overall_score >= locate_score if overall_score is not None else False
                        gps_pass = position_value in gps_values if position_value is not None else False
                        
                        # Initialize as No
                        point_row[4] = "No"  # AUTHENTICATED
                        
                        # Update PROXIMITY_TO_FACILITIES with the distance in feet
                        point_row[2] = round(distance_feet, 2)
                        
                        # Check each category and assign PROXIMITY_RANK
                        found_category = False
                        prev_cat_distance = 0
                        
                        for cat in categories:
                            # Check if point falls within this category's distance range
                            if prev_cat_distance < distance_feet <= cat['distance']:
                                found_category = True
                                point_row[3] = cat['name']  # Set PROXIMITY_RANK
                                
                                # Check validation criteria if the category has pass values
                                passes_validation = True
                                if locate_pass and gps_pass:  # Basic validation checks
                                    if cat['pass_values']:  # If category has specific pass values
                                        # Get pass field value for the current main
                                        if pass_field and near_fid >= 0:
                                            with arcpy.da.SearchCursor(spire_main, [pass_field], 
                                                                     f"OBJECTID = {near_fid}") as main_cursor:
                                                for main_row in main_cursor:
                                                    if main_row[0] not in cat['pass_values']:
                                                        passes_validation = False
                                                    break
                                    
                                    # Set AUTHENTICATED based on category setting and validation
                                    if passes_validation and cat['authenticate']:
                                        point_row[4] = "Yes"
                                        
                                results[cat['name']] += 1
                                arcpy.AddMessage(f"Point {point_id} in category {cat['name']} "
                                               f"(distance: {distance_feet:.2f} ft, authenticated: {point_row[4]})")
                                break
                            
                            prev_cat_distance = cat['distance']
                        
                        if not found_category:
                            point_row[3] = "X"
                        
                        # Update the row
                        point_cursor.updateRow(point_row)
            
            # Create output summary table
            output_table = os.path.join(arcpy.env.workspace, "UTTO_Analysis_Results")
            if arcpy.Exists(output_table):
                arcpy.Delete_management(output_table)
            
            arcpy.CreateTable_management(arcpy.env.workspace, "UTTO_Analysis_Results")
            arcpy.AddField_management(output_table, "CATEGORY", "TEXT")
            arcpy.AddField_management(output_table, "POINTS_PASSED", "LONG")
            arcpy.AddField_management(output_table, "PASS_RATE", "DOUBLE")
            arcpy.AddField_management(output_table, "MAX_DISTANCE", "DOUBLE")
            
            
            # Report detailed results and populate output table
            arcpy.AddMessage("\n=== Processing Results ===")
            arcpy.AddMessage(f"Total points processed: {processed_points} of {total_points}")
            
            total_passing = 0
            with arcpy.da.InsertCursor(output_table, ["CATEGORY", "POINTS_PASSED", "PASS_RATE", "MAX_DISTANCE"]) as cursor:
                for category in categories:
                    passing = results[category['name']]
                    total_passing += passing
                    pass_rate = (passing / total_points * 100) if total_points > 0 else 0
                    
                    # Add to output table
                    cursor.insertRow([
                        category['name'],
                        passing,
                        pass_rate,
                        category['distance']
                    ])
                    
                    arcpy.AddMessage(f"\nCategory {category['name']}:")
                    arcpy.AddMessage(f"- Passing points: {passing}")
                    arcpy.AddMessage(f"- Pass rate: {pass_rate:.1f}%")
                    arcpy.AddMessage(f"- Maximum distance: {category['distance']} ft")
            
            overall_pass_rate = (total_passing / total_points * 100) if total_points > 0 else 0
            arcpy.AddMessage(f"\nOverall Statistics:")
            arcpy.AddMessage(f"- Total passing points: {total_passing}")
            arcpy.AddMessage(f"- Overall pass rate: {overall_pass_rate:.1f}%")
            arcpy.AddMessage(f"- Required threshold: {pass_threshold:.1f}%")
            
            arcpy.AddMessage(f"\nOutput table created: {output_table}")
            arcpy.AddMessage("Fields have been updated in the input feature class.")
            
            if overall_pass_rate >= pass_threshold:
                arcpy.AddMessage("PASSED: Overall pass rate meets or exceeds threshold")
            else:
                arcpy.AddMessage("FAILED: Overall pass rate below threshold")

        except arcpy.ExecuteError:
            arcpy.AddError(arcpy.GetMessages(2))
        except Exception as e:
            arcpy.AddError(f"An error occurred: {str(e)}")
