#!/bin/bash

#check for files in /work/osgpool/halld/to_be_scrubbed/ and delete directories in /work/osgpool/halld/REQUESTEDMC_OUTPUT/ that end with that file name
for file in /work/osgpool/halld/to_be_scrubbed/*; do
    if [ -f "$file" ]; then
        filename=$(basename "$file")
        echo "Processing file: $filename"
        # Remove the file extension
        dirname="${filename%.*}"
        # Check if the directory exists and remove it
        dir_to_remove=$(ls -d /work/osgpool/halld/REQUESTEDMC_OUTPUT/*$dirname)
        if [ -d "$dir_to_remove" ]; then
            echo "Removing directory: $dir_to_remove"
            rm -rf "$dir_to_remove"
            if [ $? -eq 0 ]; then
                echo rm $file
                rm $file
            else
                echo "Failed to remove directory: $dir_to_remove"
            fi
        else
            echo "Directory does not exist: $dir_to_remove"
        fi
    else
        echo "Skipping non-file: $file"
    fi
done
echo ""
echo "Finished processing files in /work/osgpool/halld/to_be_scrubbed/"
echo "All specified directories have been removed."
echo "Cleanup complete."