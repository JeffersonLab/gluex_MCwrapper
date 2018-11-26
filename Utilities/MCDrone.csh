#!/bin/bash -f                                                                                                                                                                                                      

source /osgpool/halld/tbritton/local_setup.sh

if [[ `ps all -u tbritton | grep MCDrone.csh | grep -v grep | wc -l` == 2 ]]; then

    export PATH=/apps/bin:${PATH};
    $MCWRAPPER_CENTRAL/Utilities/MCDispatcher.py autolaunch
#else
#    echo "too many running"

fi
