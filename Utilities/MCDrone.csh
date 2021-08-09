#!/bin/bash -f
if [[ -f /osgpool/halld/tbritton/.ALLSTOP ]]; then
    echo "ALL STOP DETECTED"
fi

echo `ps all -u tbritton | grep MCDrone.csh`
echo `ps all -u tbritton | grep MCDrone.csh | grep -v grep | wc -l`

if [[ `ps all -u tbritton | grep MCDrone.csh | grep -v grep | wc -l` == 2 ]]; then
    cd /tmp/ #/volatile/halld/home/tbritton/
    source /osgpool/halld/tbritton/local_setup.sh
    export PATH=/apps/bin:${PATH};
    export PATH=/site/bin:${PATH};
    $MCWRAPPER_CENTRAL/Utilities/MCDrone.py
else
    echo "too many running"

fi
