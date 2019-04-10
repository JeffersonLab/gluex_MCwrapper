#!/bin/bash -f                                                                                                                                                                                                      
cd /volatile/halld/home/tbritton/
source /osgpool/halld/tbritton/local_setup.sh

if [[ -f /osgpool/halld/tbritton/.ALLSTOP ]]; then
    echo "ALL STOP DETECTED"
fi

if [[ `ps all -u tbritton | grep MCDrone.csh | grep -v grep | wc -l` == 2 ]]; then

    export PATH=/apps/bin:${PATH};
    $MCWRAPPER_CENTRAL/Utilities/MCDrone.py
#else
#    echo "too many running"

fi
