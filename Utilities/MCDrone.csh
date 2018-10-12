#!/bin/bash -f                                                                                                                                                                                                      

source /osgpool/halld/tbritton/local_setup.sh

if [[ `ps all -u tbritton | grep MCDispatcher.py | wc -l` == 1 ]]; then
    $MCWRAPPER_CENTRAL/Utilities/MCDispatcher.py autolaunch
fi