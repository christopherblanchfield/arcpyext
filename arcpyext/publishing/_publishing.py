# coding=utf-8
"""This module contains helper functions related to publishing."""

# Python 2/3 compatibility
# pylint: disable=wildcard-import,unused-wildcard-import,wrong-import-order,wrong-import-position,no-name-in-module
from __future__ import (absolute_import, division, print_function, unicode_literals)
from future.builtins.disabled import *
from future.builtins import *
from future.standard_library import install_aliases
install_aliases()
# pylint: enable=wildcard-import,unused-wildcard-import,wrong-import-order,wrong-import-position,no-name-in-module

import os

import arcpy

from ..exceptions import MapDataSourcesBrokenError, ServDefDraftCreateError
from .._multiprocessing import Process


def check_analysis(analysis):
    if not analysis["errors"] == {}:
        err_message_list = []
        for ((message, code), layerlist) in analysis["errors"].iteritems():
            if layerlist == None:
                err_message_list.append("{message} (CODE {code})".format(message=message, code=code))
            else:
                err_message_list.append("{message} (CODE {code}) applies to: {layers}".format(
                    message=message, code=code, layers=", ".join([layer.name for layer in layerlist])))
        raise ServDefDraftCreateError("Analysis Errors: \n{errs}".format(errs="\n".join(err_message_list)))


def convert_pro_map_to_service_draft(path_proj_or_map,
                                     sd_draft_path,
                                     service_name,
                                     folder_name=None,
                                     summary=None,
                                     copy_data_to_server=False,
                                     portal_folder=None):
    from ..mapping import is_valid

    if isinstance(path_proj_or_map, arcpy.mp.ArcGISProject):
        # assume we want to publish the first map
        map_obj = path_proj_or_map.listMaps()[0]
    elif isinstance(path_proj_or_map, arcpy._mp.Map):
        # got a map, all good to go
        # have to grab the class from the internal module
        map_obj = path_proj_or_map
    else:
        # assume it's a path
        map_obj = arcpy.mp.ArcGISProject(path_proj_or_map).listMaps()[0]

    if len(map_obj.listBrokenDataSources()) > 0:
        raise MapDataSourcesBrokenError("One or more layers or tables have broken data sources.")

    if os.path.exists(sd_draft_path):
        os.remove(sd_draft_path)

    draft = arcpy.sharing.CreateSharingDraft(
        'STANDALONE_SERVER',  # This is a fixed value and doesn't do anything
        'MAP_SERVICE',
        service_name,
        map_obj)

    draft.offline = True
    draft.serverFolder = folder_name
    draft.portalFolder = portal_folder
    draft.exportToSDDraft(sd_draft_path)

    return sd_draft_path


def convert_pro_map_to_vector_tile_draft(path_proj_or_map,
                                         sd_draft_path,
                                         service_name,
                                         folder_name=None,
                                         summary=None,
                                         copy_data_to_server=False,
                                         portal_folder=None):
    from ..mapping import is_valid

    if isinstance(path_proj_or_map, arcpy.mp.ArcGISProject):
        # assume we want to publish the first map
        map_obj = path_proj_or_map.listMaps()[0]
    elif isinstance(path_proj_or_map, arcpy._mp.Map):
        # got a map, all good to go
        # have to grab the class from the internal module
        map_obj = path_proj_or_map
    else:
        # assume it's a path
        map_obj = arcpy.mp.ArcGISProject(path_proj_or_map).listMaps()[0]

    if len(map_obj.listBrokenDataSources()) > 0:
        raise MapDataSourcesBrokenError("One or more layers or tables have broken data sources.")

    if os.path.exists(sd_draft_path):
        os.remove(sd_draft_path)

    draft = map_obj.getWebLayerSharingDraft('HOSTING_SERVER', 'TILE', service_name)

    draft.offline = True
    draft.serverFolder = folder_name
    draft.portalFolder = portal_folder
    draft.exportToSDDraft(sd_draft_path)

    return sd_draft_path


def convert_pro_map_to_hosted_feature_draft(path_proj_or_map,
                                           sd_draft_path,
                                           service_name,
                                           folder_name=None,
                                           summary=None,
                                           copy_data_to_server=False,
                                           portal_folder=None):
    from ..mapping import is_valid

    if isinstance(path_proj_or_map, arcpy.mp.ArcGISProject):
        # assume we want to publish the first map
        map_obj = path_proj_or_map.listMaps()[0]
    elif isinstance(path_proj_or_map, arcpy._mp.Map):
        # got a map, all good to go
        # have to grab the class from the internal module
        map_obj = path_proj_or_map
    else:
        # assume it's a path
        map_obj = arcpy.mp.ArcGISProject(path_proj_or_map).listMaps()[0]

    if len(map_obj.listBrokenDataSources()) > 0:
        raise MapDataSourcesBrokenError("One or more layers or tables have broken data sources.")

    if os.path.exists(sd_draft_path):
        os.remove(sd_draft_path)

    draft = map_obj.getWebLayerSharingDraft('HOSTING_SERVER', 'FEATURE', service_name)

    draft.offline = True
    draft.serverFolder = folder_name
    draft.portalFolder = portal_folder
    draft.exportToSDDraft(sd_draft_path)

    return sd_draft_path


def convert_desktop_map_to_service_draft(map_doc,
                                         sd_draft_path,
                                         service_name,
                                         folder_name=None,
                                         summary=None,
                                         copy_data_to_server=False,
                                         portal_folder=None):
    """
    Convert a Map Document to a service definition draft.

    portal_folder: ignored on ArcGIS Desktop
    """

    from ..mapping import is_valid

    if not isinstance(map_doc, arcpy.mapping.MapDocument):
        map_doc = arcpy.mapping.MapDocument(map_doc)

    if not is_valid(map_doc):
        raise MapDataSourcesBrokenError("One or more layers have broken data sources.")

    if os.path.exists(sd_draft_path):
        os.remove(sd_draft_path)

    analysis = arcpy.mapping.CreateMapSDDraft(map_doc,
                                              sd_draft_path,
                                              service_name,
                                              server_type="ARCGIS_SERVER",
                                              copy_data_to_server=copy_data_to_server,
                                              folder_name=folder_name,
                                              summary=summary)

    check_analysis(analysis)

    analysis = arcpy.mapping.AnalyzeForSD(sd_draft_path)
    check_analysis(analysis)

    return sd_draft_path


def convert_service_draft_to_staged_service(sd_draft, sd_path):
    """
    Converts a Service Definition Draft (*.sddraft) to a Service Definiton (*.sd).
    """

    # The StageService toolbox seems unreliable when it comes to connecting to Enterprise Geodatabases.
    # We're spinning it up here in a sub-process in a (perhaps vain) attempt to improve reliability.

    if hasattr(sd_draft, "file_path"):
        sd_draft_path = sd_draft.file_path
    else:
        sd_draft_path = sd_draft

    p = Process(target=arcpy.StageService_server, args=(sd_draft_path, sd_path))

    if os.path.exists(sd_path):
        os.remove(sd_path)

    p.start()
    p.join()

    if p.exception:
        error, traceback = p.exception
        raise error


def convert_toolbox_to_service_draft(toolbox_path,
                                     sd_draft_path,
                                     get_result_fn,
                                     service_name,
                                     folder_name=None,
                                     summary=None):
    # import and run the package
    arcpy.ImportToolbox(toolbox_path)
    # optionally allow a list of results
    if not callable(get_result_fn):
        result = [fn() for fn in get_result_fn]
    else:
        result = get_result_fn()

    # create the sddraft
    analysis = arcpy.CreateGPSDDraft(result,
                                     sd_draft_path,
                                     service_name,
                                     server_type="ARCGIS_SERVER",
                                     copy_data_to_server=False,
                                     folder_name=folder_name,
                                     summary=summary)
    check_analysis(analysis)
    # and analyse it
    analysis = arcpy.mapping.AnalyzeForSD(sd_draft_path)
    check_analysis(analysis)

    return sd_draft_path
