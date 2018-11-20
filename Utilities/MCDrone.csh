#!/bin/bash -f                                                                                                                                                                                                      

source /osgpool/halld/tbritton/local_setup.sh

if [[ `ps all -u tbritton | grep MCDispatcher.py | grep -v grep | wc -l` == 0 ]]; then
    export PATH=/apps/bin:${PATH};
    $MCWRAPPER_CENTRAL/Utilities/MCDispatcher.py autolaunch
fi