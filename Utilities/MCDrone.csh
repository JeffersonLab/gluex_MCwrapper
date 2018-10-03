#!/bin/csh -f

source /osgpool/halld/tbritton/local_setup.csh

if (`ps all -u tbritton | grep MCDispatcher.py` == "" ) then
    $MCWRAPPER_CENTRAL/Utilities/MCDispatcher.py autolaunch
endif