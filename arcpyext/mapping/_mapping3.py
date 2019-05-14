# coding=utf-8
"""This module contains extended functionality for related to the arcpy.mp module."""

# Python 2/3 compatibility
# pylint: disable=wildcard-import,unused-wildcard-import,wrong-import-order,wrong-import-position
from __future__ import (absolute_import, division, print_function, unicode_literals)
from future.builtins.disabled import *
from future.builtins import *
from future.standard_library import install_aliases
install_aliases()
# pylint: enable=wildcard-import,unused-wildcard-import,wrong-import-order,wrong-import-position

# Standard lib imports
import logging
import re

from itertools import zip_longest

# Third-party imports
import arcpy

# Local imports
from ..exceptions import MapLayerError, DataSourceUpdateError, UnsupportedLayerError, ChangeDataSourcesError
from ..arcobjects import init_arcobjects_context, destroy_arcobjects_context, list_layers

# Configure module logging
logger = logging.getLogger("arcpyext.mp")


def change_data_sources(project, data_sources):
    """ """
    # make sure the project is a project, not a path
    project = open_document(project)

    errors = []

    # match map with data sources
    for proj_map, map_data_sources in zip_longest(project.listMaps(), data_sources):

        if not 'layers' in map_data_sources or not 'tableViews' in map_data_sources:
            raise ChangeDataSourcesError("Data sources dictionary does not contain both layers and tableViews keys")

        layers = proj_map.listLayers()
        layer_sources = map_data_sources["layers"]

        if layer_sources == None or len(layers) != len(layer_sources):
            raise ChangeDataSourcesError("Number of layers does not match number of data sources.")

        for layer, layer_source in zip_longest(layers, layer_sources):
            try:
                if layer_source == None:
                    continue

                logger.debug("Layer {0}: Attempting to change workspace path".format(layer.longName))
                logger.debug("Old connectionProperties {0}".format(layer.connectionProperties))
                _change_data_source(layer, layer_source)
                logger.debug("Layer {0}: connectionProperties updated to: {1}".format(layer.name,
                                                                                          layer_source))

                if layer.supports("dataSource"):
                    logger.debug("Layer {0}: New datasource: {1}".format(layer.longName, layer.dataSource))

            #TODO: Handle KeyError and AttributeError for badly written configs
            except MapLayerError as e:
                errors.append(e)

        data_tables = proj_map.listTables()
        data_table_sources = map_data_sources["tableViews"]

        if not len(data_tables) == len(data_table_sources):
            raise ChangeDataSourcesError("Number of data tables does not match number of data table data sources.")

        for data_table, layer_source in zip_longest(data_tables, data_table_sources):
            try:
                if layer_source == None:
                    continue

                logger.debug("Data Table {0}: Attempting to change workspace path".format(data_table.name).encode(
                    "ascii", "ignore"))
                logger.debug("Old connectionProperties {0}".format(data_table.connectionProperties).encode(
                    "ascii", "ignore"))
                _change_data_source(data_table, layer_source.get("connectionProperties"))
                logger.debug("Data Table {0}: Workspace path updated to: {1}".format(
                    data_table.name, layer_source.get("connectionProperties")))

            except MapLayerError as mle:
                errors.append(mle)

    if not len(errors) == 0:
        raise ChangeDataSourcesError("A number of errors were encountered whilst change layer data sources.", errors)


def compare(map_a, map_b):
    """Compares two map documents.

    Outputs a list describing any differences

    :param map_a: A map to compare
    :type map_a: arcpy.mp.ArcGISProject
    :param map_b: Another version of the same map to compare
    :type map_b: arcpy.mp.ArcGISProject
    :returns: dict

    """

    #
    # Compare data frames
    #
    def compare_data_frames():

        map_count_changed = 301
        data_frame_cs_code_changed = 302
        data_frame_cs_name_changed = 303
        data_frame_cs_type_changed = 304
        diff = []

        try:

            map_a_maps = [x for x in map_a.listMaps()]
            map_b_maps = [x for x in map_b.listMaps()]

            map_a_maps_len = len(map_a_maps)
            map_b_maps_len = len(map_b_maps)

            if map_b_maps_len == 0 or map_a_maps_len != map_b_maps_len:
                diff.append({"type": map_count_changed, "was": map_a_maps_len, "now": map_b_maps_len})

            for index, a in enumerate(map_a_maps):

                b = map_b_maps[index]

                if a.defaultCamera.getExtent().spatialReference.factoryCode != b.defaultCamera.getExtent(
                ).spatialReference.factoryCode:
                    diff.append({
                        "type": data_frame_cs_code_changed,
                        "was": a.defaultCamera.getExtent().spatialReference.factoryCode,
                        "now": b.defaultCamera.getExtent().spatialReference.factoryCode,
                    })

                if a.defaultCamera.getExtent().spatialReference.type != b.defaultCamera.getExtent(
                ).spatialReference.type:
                    diff.append({
                        "type": data_frame_cs_type_changed,
                        "was": a.defaultCamera.getExtent().spatialReference.type,
                        "now": b.defaultCamera.getExtent().spatialReference.type,
                    })

                if a.defaultCamera.getExtent().spatialReference.name != b.defaultCamera.getExtent(
                ).spatialReference.name:
                    diff.append({
                        "type": data_frame_cs_name_changed,
                        "was": a.defaultCamera.getExtent().spatialReference.name,
                        "now": b.defaultCamera.getExtent().spatialReference.name,
                    })

        except Exception:
            logger.exception("Error comparing data frames")

        finally:
            return diff

    def compare_layers():
        """
        Compares layers for differences between versions of the same layer set on a map.
        """

        try:

            # Scalar equality check
            eq = lambda a, b, k: b[k] == a[k] if k in a and k in b else False

            def _sort(obj):
                """
                Dictionary equality check. Sort is used to ensure consistent order before comparision
                """

                if isinstance(obj, dict):
                    return sorted((k, _sort(v)) for k, v in obj.items())
                if isinstance(obj, list):
                    return sorted(_sort(x) for x in obj)
                else:
                    return obj

            arrEq = lambda a, b, k: _sort(a[k]) == _sort(b[k]) if k in a and k in b else False

            # Who are you? Who am I?
            def _express_diff(a, b, k, type):
                return {"type": type, "was": a[k] if k in a else None, "now": b[k] if k in b else None}

            def _layer_diff(a, b):

                # Layer change reasons
                layer_id_changed = 401
                layer_name_changed = 402
                layer_datasource_changed = 403
                layer_visibility_changed = 404
                layer_fields_changed = 405
                layer_definition_query_changed = 406

                diff = []

                tests = [
                    {
                        "layer_prop_name": "id",
                        "change_id": layer_id_changed
                    },
                    {
                        "layer_prop_name": "name",
                        "change_id": layer_name_changed
                    },
                    {
                        "layer_prop_name": "visible",
                        "change_id": layer_visibility_changed
                    },
                    {
                        "layer_prop_name": "workspacePath",
                        "change_id": layer_datasource_changed
                    },
                    {
                        "layer_prop_name": "datasetName",
                        "change_id": layer_datasource_changed
                    },
                    {
                        "layer_prop_name": "database",
                        "change_id": layer_datasource_changed
                    },
                    {
                        "layer_prop_name": "server",
                        "change_id": layer_datasource_changed
                    },
                    {
                        "layer_prop_name": "service",
                        "change_id": layer_datasource_changed
                    },
                    {
                        "layer_prop_name": "definitionQuery",
                        "change_id": layer_definition_query_changed
                    },
                    {
                        # Array fields must provide a hash function. This is used to create a UID that can be used for hashset comparison.
                        # An unhash function must also be provided to reverse lookup the raw dict from a hash ID
                        "layer_prop_name": "fields",
                        "change_id": layer_fields_changed,
                        "array": True,
                        "hash": lambda _dict: "%s|%s|%s" % (_dict['index'], _dict['name'], _dict['visible']),
                        "unhash": lambda hash: hash.split("|")[0]
                    }
                ]

                # Test each property for changes
                for test in tests:

                    k = test["layer_prop_name"]
                    v = test["change_id"]
                    is_array = test["array"] == True if "array" in test else False

                    if k in a and k in b:

                        if is_array == True:

                            # Set comparsion. Find the difference between A and B
                            hash = test["hash"]
                            unhash = test["unhash"]

                            hashed_a = [hash(_dict) for _dict in a[k]]
                            hashed_b = [hash(_dict) for _dict in b[k]]

                            if set(hashed_a) != set(hashed_b):

                                was = list(set(hashed_a).difference(set(hashed_b)))
                                now = list(set(hashed_b).difference(set(hashed_a)))

                                def inflate(arr, index):
                                    return [x for x in arr if x['index'] == int(index)][0]

                                was = [inflate(a[k], x) for x in [unhash(x) for x in was]]
                                now = [inflate(b[k], x) for x in [unhash(x) for x in now]]

                                diff.append({"type": v, "was": was, "now": now})

                        else:
                            if not eq(a, b, k):
                                diff.append(_express_diff(a, b, k, v))
                    else:
                        diff.append(_express_diff(a, b, k, v))

                return diff

            a = list_document_data_sources(map_a)
            b = list_document_data_sources(map_b)

            # Flatten layer structure, only compare layers on first map
            a_layers = [item for sublist in a[0]['layers'] for item in sublist if item is not None]
            b_layers = [item for sublist in b[0]['layers'] for item in sublist if item is not None]

            # To correlate a layer in map a and map b, we run a series of specificity tests. Tests are ordered from
            # most specific, to least specific. These tests apply a process of elimination methodology to correlate layers
            # between the 2 maps
            added = []
            updated = []
            removed = []
            resolved_a = {}
            resolved_b = {}
            is_resolved_a = lambda x: x['name'] in resolved_a
            is_resolved_b = lambda x: x['name'] in resolved_b
            same_id = lambda a, b: eq(a, b, 'id')
            same_name = lambda a, b: eq(a, b, 'name')
            same_datasource = lambda a, b: eq(a, b, 'datasetName')

            tests = [
                {
                    'fn': lambda a, b: b if same_id(a, b) and same_name(a, b) and same_datasource(a, b) else None,
                    'desc': "same id/name and datasource. Unchanged",
                    'ignore': True
                },
                {
                    'fn':
                    lambda a, b: b if same_id(a, b) and same_name(a, b) and not is_resolved_a(a) and not is_resolved_b(b) else None,
                    'desc':
                    "same name and id, datasource changed"
                },
                {
                    'fn':
                    lambda a, b: b if same_id(a, b) and same_datasource(a, b) and not is_resolved_a(a) and not is_resolved_b(b) else None,
                    'desc':
                    "same id and datasource, name changed"
                },
                {
                    # TODO this should be skipped if we can verify that fixed layer IDs are not used
                    'fn': lambda a, b: b if same_id(a, b) and not is_resolved_a(a) and not is_resolved_b(b) else None,
                    'desc': "same id. Assumed valid if fixed data sources enabled"
                },
                {
                    'fn':
                    lambda a, b: b if same_name(a, b) and same_datasource(a, b) and not is_resolved_a(a) and not is_resolved_b(b) else None,
                    'desc':
                    "same name and datasource, id changed"
                },
                {
                    'fn': lambda a, b: b if same_name(a, b) and not is_resolved_a(a) and not is_resolved_b(b) else None,
                    'desc': "same name, id/datasource changed"
                },
            ]

            # For every b layer, run a series of tests to find the correlating A layer (if any)
            for b_layer in b_layers:
                match = None

                # Find A layer that correlates to B layer
                for a_layer in a_layers:
                    for index, test in enumerate(tests):
                        matcher = test['fn']
                        desc = test['desc']
                        ignore = True if 'ignore' in test and test['ignore'] == True else False
                        match = matcher(a_layer, b_layer)
                        if match is not None:

                            # Updated layer
                            resolved_a[a_layer['name']] = True
                            resolved_b[b_layer['name']] = True
                            b_layer['diff'] = _layer_diff(a_layer, b_layer)

                            # Add layers that have changes (and are not skipped by the ignore flag) to the result list
                            if not ignore or len(b_layer['diff']) > 0:
                                updated.append(b_layer)
                                break

                # New layer
                if match is None and not is_resolved_b(b_layer):
                    resolved_b[b_layer['name']] = True
                    added.append(b_layer)

            # Removed layers
            for a_layer in a_layers:
                if not is_resolved_a(a_layer):
                    resolved_a[a_layer['name']] = True
                    removed.append(a_layer)

        except Exception:
            logger.exception("Error comparing layers")

        finally:
            return {'added': added, 'updated': updated, 'removed': removed}

    return {'dataFrames': compare_data_frames(), 'layers': compare_layers()}


def create_replacement_data_sources_list(document_data_sources_list,
                                         data_source_templates,
                                         raise_exception_no_change=False):

    # Here we are rearranging the data_source_templates so that the match criteria can be compared as a set - in case there are more than one.
    template_sets = [
        dict(list(template.items()) + [("matchCriteria", set(template["matchCriteria"].items()))])
        for template in data_source_templates
    ]

    # freeze values in dict for set comparison
    def freeze(d):
        """Freezes dicts and lists for set comparison."""
        if isinstance(d, dict):
            return frozenset((key, freeze(value)) for key, value in d.items())
        elif isinstance(d, list):
            return tuple(freeze(value) for value in d)
        return d

    def match_new_data_source(item):
        if item == None:
            return None

        new_conn = None
        for template in template_sets:
            # The item variable is a layer object which contains a fields property (type list) that can't be serialised and used in set operations
            # It is not required for datasource matching, so exclude it from the the set logic
            if template["matchCriteria"].issubset(set(freeze(item))):
                new_conn = template["dataSource"]
                break
        if new_conn == None and raise_exception_no_change:
            raise RuntimeError("No matching data source was found for layer")
        return new_conn

    return [{
        "layers": [match_new_data_source(layer) for layer in df["layers"]],
        "tableViews": [match_new_data_source(table) for table in df["tableViews"]]
    } for df in document_data_sources_list]


def list_document_data_sources(project):
    """List the data sources for each layer or table view of the specified map.

    Outputs a list of of dictionaries (each dictionary represents a map on the project), with each dictionary
    containing two keys, "layers" and "tableViews".

    "layers" contains an array, with each element a dictionary of layer details relevant to that layer's connection to
    its data source.

    "tableViews" is also an array, where each element is a dictionary of table view details relevant to that table
    view's connection to its data source.

    The order of array elements is as displayed in the ArcMap table of contents.

    An example of the output format is the following::

        [
            {
            # Map number one
                "layers": [
                    {
                        # Layer number one
                        "id":               "Layer ID",
                        "name":             "Layer Name",
                        "longName":         "Layer Group/Layer Name",
                        "datasetName":      "(Optional) dataset name",
                        "dataSource":       "(Optional) data source name",
                        "serviceType":      "(Optional) service type, e.g. SDE, MapServer, IMS",
                        "userName":         "(Optional) user name",
                        "server":           "(Optional) server address/hostname",
                        "service":          "(Optional) name or number of the ArcSDE Service",
                        "database":         "(Optional) name of the database",
                        "workspacePath":    "(Optional) workspace path"
                        "visible":          "(Optional) visibility"
                        "definitionQuery":  "definition query on the layer"
                    },
                    # ...more layers
                ],
                "tableViews": [
                    {
                        "datasetName":          "dataset name",
                        "dataSource":           "data source",
                        "definitionQuery":      "definition query on the table",
                        "workspacePath":        "workspace path"
                    }
                ]
            }
            # ...more maps
        ]

    :param project: The map to gather data source connection details about
    :type project: arcpy.mp.ArcGISProject
    :returns: array
    """

    # make sure the project is a project, not a path
    project = open_document(project)

    return [{
        "layers": [_get_layer_details(layer) for layer in mp.listLayers()],
        "tableViews": [_get_table_details(table) for table in mp.listTables()]
    } for mp in project.listMaps()]


def open_document(project):
    """Open an ArcGIS Pro Project from a given path.
    
    If the path is already a Project, this is a no-op.
    """

    if isinstance(project, arcpy.mp.ArcGISProject):
        return project
    
    return arcpy.mp.ArcGISProject(project)


def validate_pro_project(project):
    # make sure the project is a project, not a path
    project = open_document(project)

    broken_layers = project.listBrokenDataSources()

    if len(broken_layers) > 0:
        logger.debug("Map '{0}': Broken data sources:".format(project.filePath))
        for layer in broken_layers:
            logger.debug(" {0}".format(layer.name))
            if not hasattr(layer, "supports"):
                #probably a TableView
                logger.debug("  workspace: {0}".format(layer.workspacePath))
                logger.debug("  datasource: {0}".format(layer.dataSource))
                continue

            #Some sort of layer
            if layer.supports("workspacePath"):
                logger.debug("  workspace: {0}".format(layer.workspacePath))
            if layer.supports("dataSource"):
                logger.debug("  datasource: {0}".format(layer.dataSource))

        return False

    return True


def _change_data_source(layer, new_props):
    try:
        existing_conn_props = layer.connectionProperties

        layer.updateConnectionProperties(existing_conn_props, new_props)

    except Exception as e:
        raise DataSourceUpdateError("Exception raised internally by ArcPy", layer, e)

    if hasattr(layer, "isBroken") and layer.isBroken:
        raise DataSourceUpdateError("Layer is now broken.", layer)


def _get_layer_details(layer):
    if layer.isGroupLayer and not layer.isNetworkAnalystLayer:
        return None

    details = {"name": layer.name, "longName": layer.longName}

    if layer.supports("datasetName"):
        details["datasetName"] = layer.datasetName

    if layer.supports("dataSource"):
        details["dataSource"] = layer.dataSource

    if layer.supports("serviceProperties"):
        details["serviceType"] = layer.serviceProperties["ServiceType"]

        if "UserName" in layer.serviceProperties:
            # File GDB doesn't support username and throws an exception
            details["userName"] = layer.serviceProperties["UserName"]

        if layer.serviceProperties["ServiceType"].upper() == "SDE":
            details["server"] = layer.serviceProperties["Server"]
            details["service"] = layer.serviceProperties["Service"]
            details["database"] = layer.serviceProperties["Database"]

    if layer.supports("workspacePath"):
        details["workspacePath"] = layer.workspacePath

    if layer.supports("visible"):
        details["visible"] = layer.visible

    if layer.supports("definitionQuery"):
        details["definitionQuery"] = layer.definitionQuery

    if layer.supports("connectionProperties"):
        details["connectionProperties"] = layer.connectionProperties

    # Fields
    # @see https://desktop.arcgis.com/en/arcmap/10.4/analyze/arcpy-functions/describe.htm
    # Wrapped in a try catch, because fields can only be resolved if the layer's datasource is valid.
    try:
        desc = arcpy.Describe(layer)
        logger.debug(desc)
        if desc.dataType == "FeatureLayer":
            field_info = desc.fieldInfo
            details["fields"] = []
            for index in range(0, field_info.count):
                details["fields"].append({
                    "index": index,
                    "name": field_info.getFieldName(index),
                    "visible": field_info.getVisible(index) == "VISIBLE"
                })
    except Exception:
        logger.exception("Could not resolve layer fields ({0}). The layer datasource may be broken".format(layer.name))

    return details


def _get_table_details(table):
    return {
        "connectionProperties": table.connectionProperties,
        "dataSource": table.dataSource,
        "definitionQuery": table.definitionQuery,
        "name": table.name
    }
