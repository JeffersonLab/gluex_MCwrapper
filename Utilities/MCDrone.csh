#!/bin/bash -f
if [[ -f /osgpool/halld/tbritton/.ALLSTOP ]]; then
    echo "ALL STOP DETECTED"
fi

if [[ `ps all -u tbritton | grep MCDrone.csh | grep -v grep | wc -l` == 2 ]]; then
    cd /volatile/halld/home/tbritton/
    source /osgpool/halld/tbritton/local_setup.sh
    export PATH=/apps/bin:${PATH};
    export PATH=/site/bin:${PATH};
    $MCWRAPPER_CENTRAL/Utilities/MCDrone.py
#else
#    echo "too many running"

fi
