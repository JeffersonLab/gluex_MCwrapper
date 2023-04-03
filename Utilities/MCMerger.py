"""
Author: Darius Darulis
Date: 2022

A simple-ish script to merge together outputs produced by the MCWrapper.
The different types of MCWrapper outputs are merged using their native
tools, i.e. hadd for root files.
If no such option exists, or if such options are too inefficient, then the files are simply zipped together. 
This is done per run, and in addition root files are grouped by 
reaction. 

Takes input path and output path as command line arguments. 
"""
import os
import re
from functools import reduce
import sys
import subprocess
import argparse
from collections import defaultdict


bash = {}

def dir_path(path):
    """Provide type defition for command line path arguments."""
    print("given path: ", path)
    if os.path.isdir(path):
        return path
    else:
        raise argparse.ArgumentTypeError(f"{path} is not a valid path.")

def add_bash(func):
    """Add decorated function to the bash action dictionary."""
    bash[func.__name__] = func
    return func
@add_bash
def bash_root(name_map, path, mc_dir):
    """Merge root files in mc_dir."""
    return_code = 0
    for dir_type in name_map.keys():
        print(f"Path: {path}    dir_type: {dir_type}")
        if not isinstance(dir_type,str):
            continue
        subprocess.run([f"mkdir -p {path + dir_type}"], shell=True)
        if dir_type == "trees":
            for tup in name_map["trees"].keys():
                fold_name, suffix = tup[0], tup[1]
                fold_name = fold_name.rstrip("_")
                return_code += subprocess.run([f"mkdir {path + '/' + dir_type + '/' +  fold_name}"], shell=True).returncode
                for run in name_map["trees"][tup]["run_nums"]:
                    success = subprocess.run([f"hadd -v 1 -f {path + '/' + dir_type + '/' +  fold_name + '/' + tup[0] + run + tup[1]} {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    return_code += success.returncode
                    #if success.returncode == 0:
                     #   good_runs.append(run)
        else:
            subprocess.run([f"mkdir -p {path + dir_type}"] , shell=True)
            for tup in name_map[dir_type].keys():
                for run in name_map[dir_type][tup]["run_nums"]:
                    success = subprocess.run([f"hadd -v 1 -f {path + '/' + dir_type + '/' +  tup[0] + run + tup[1]} {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    return_code += success.returncode
    return return_code

@add_bash
def bash_hddm_merge(name_map, path, mc_dir):
    """Merge hddm files in mc_dir using the merge_hddm.py script."""
    return_code = 0
    MCWRAPPER_BOT_HOME="/scigroup/mcwrapper/gluex_MCwrapper/"
    subprocess.run([f"mkdir -p {path}"] , shell=True)
    for tup in name_map.keys():
        for run in name_map[tup]["run_nums"]:
            print(f"hddm add {run}",flush=True)
            success =  subprocess.run([f"python2 "+MCWRAPPER_BOT_HOME+f"/Utilities/merge_hddm.py {path + tup[0] + run + tup[1]} {mc_dir + '/hddm/' + tup[0] + run}*{tup[1]}"], shell=True)
            return_code += success.returncode
    return return_code

@add_bash
def bash_hddm(name_map, path, mc_dir):
    """Bundle hddm files in mc_dir using tar."""
    return_code = 0
    subprocess.run([f"mkdir -p {path}"] , shell=True)
    for tup in name_map.keys():
        for run in name_map[tup]["run_nums"]:
            success = subprocess.run([f"tar cvf {path  + tup[0] + run + tup[1]}.tar {mc_dir + '/'  +  'hddm' + '/' +   tup[0] + run}_*{tup[1]}"], shell=True)
            return_code += success.returncode
    return return_code


@add_bash
def bash_config(name_map, path, mc_dir):
    """Bundle config files in mc_dir."""
    return_code = 0
    for dir_type in name_map.keys():
        subprocess.run([f"mkdir -p {path + dir_type}"] , shell=True)
        for tup in name_map[dir_type].keys():
            for run in name_map[dir_type][tup]["run_nums"]:
                success = subprocess.run([f"tar cvf {path + '/' +  dir_type + '/' + tup[0] + run + tup[1]}.tar {mc_dir + '/' + 'config' + '/' +  dir_type + '/' +   tup[0] + run}_*{tup[1]}"], shell=True)
                return_code += success.returncode
    return return_code

def get_entry(file_name):
    """Return the prefix, run number, and suffix of file_name as a tuple by matching on the run number."""
    match = re.search("([0-9]{6})_[0-9]{3}", file_name)
    if match:
        prefix = file_name[:match.start()]
        run_num = match.group(1)
        suffix = file_name[match.end():]
        return (prefix, run_num, suffix)
    else:
        return None

def get_file_info(name_map, files, dir_type="root"):
    """Add prefix and suffix tuples from files into name_map."""
    exts = (".root", ".hddm", ".hdds",".conf", ".in")
    dir_dict =  defaultdict(lambda: defaultdict(set))
    for item in files:
        if item.endswith(exts):
            info =get_entry( item)
            if info:
                dir_dict[(info[0], info[2])]["run_nums"].add(info[1])
    return dir_dict

def get_run_range(name_map):   
    min_num, max_num = 100000000000000, -1
    for name in name_map.keys():
        if name == "trees":
            for reaction in name_map[name].keys():
                for run in name_map[name][reaction]["run_nums"]:
                    run = int(run)
                    min_num = min(run, min_num)
                    max_num = max(run, max_num)
        else:
            for run in name_map[name]["run_nums"]:
                run = int(run)
                min_num = min(run, min_num)
                max_num = max(run, max_num)

    return (min_num, max_num)
def recurse_name_map(name_map, path, mc_dir, hddm=False):
    """Call the corresponding bash actions for each directory in mc_dir."""
    return_code = 0
    for k, v in name_map.items():
        if k=="hddm" and hddm==True:
            k = "hddm_merge"
        if ("bash_" + k) in bash.keys():
            dir_type = re.split("/", path)[-1]
            return_code = bash["bash_" + k](name_map[k], path+k+"/", mc_dir)
    return return_code



                
def bundle(name_map, mc_dir, hddm=False):
    """
    Traverse mc_dir via name_map and perform bash actions as appropriate.
    After all actions are complete, tar up the output.
    """
    return_code = 0    
    return_code += subprocess.run([f"cd {mc_dir}; rm -rf output; mkdir -p output"], shell=True).returncode
    good_runs = []

    bundle_success = recurse_name_map(name_map, f"{mc_dir + '/' + 'output/' }", mc_dir, hddm)
    return_code += bundle_success

    return_code += subprocess.run([f"tar cvf {mc_dir + '/' +  'output.tar'} {mc_dir + '/' + 'output/' } --remove-files"], shell = True).returncode
    return return_code
   
def move(mc_dir, out_dir):
    """
    Move the bundled up mc_dir into out_dir and remove the temporary output
    from mc_dir.
    """
    n_strip_components = mc_dir.strip(os.sep).count(os.sep) + 2
    success = subprocess.run([f"mv {mc_dir + '/' + 'output.tar' } {out_dir}; cd {out_dir}; tar xvf output.tar --strip-components={n_strip_components}; rm output.tar"], shell=True)
    return success.returncode

def get_directory_structure(rootdir):
    """
    Creates a nested dictionary that represents the folder structure of rootdir
    """
    name_map = {}
    rootdir = rootdir.rstrip(os.sep)
    start = rootdir.rfind(os.sep) + 1
    for path, dirs, files in os.walk(rootdir):

        dir_type = re.split("/", path)[-1]
        folders = path[start:].split(os.sep)
        parent = reduce(dict.get, folders[:-1], name_map)
        if files:
            entry = get_file_info(name_map, files, dir_type)
            parent[folders[-1]] = entry
        else:
            subdir = dict.fromkeys(files)
            parent[folders[-1]] = subdir
    return name_map

def count_namemap_entries(name_map):
    file_no = 0
    for k, v in name_map.items():
        if isinstance(name_map[k], dict):
            file_no += count_namemap_entries(name_map[k])

        elif isinstance(name_map[k], set):
            file_no += len(name_map[k])
    return file_no

def check_success(name_map, output_path):
    mc_file_no = count_namemap_entries(name_map)
    print(f"Number of unique files to be output is {mc_file_no}")
    merged_file_no = sum([len(files) for r, d, files in os.walk(output_path)])
    print(f"Number of unique files output is {merged_file_no}")
    return mc_file_no == merged_file_no

def main(args):
        print(f"Moving from: {args.input_path} to {args.output_path}")
        if args.f==False:
            for path, dirs, files in os.walk(args.input_path):
                if "output" in dirs:
                    print("The directory in the input path might already be in the process of bundling. Use the -f flag to overwrite.")
                    return -1
                    for path, dirs, files in os.walk(args.output_path):
                        for existing_dir in ["config", "root", "hddm"]:
                            if existing_dir in dirs:
                                print("Output path might already contain bundled files. Use the -f flag to overwrite.")
                                return -1
        name_map = get_directory_structure(args.input_path)
        dir_type = re.split("/", args.input_path.rstrip(os.sep))[-1]
        bundle_success = bundle(name_map[dir_type], args.input_path.rstrip(os.sep), args.hddm)
        move_success = move(args.input_path, args.output_path)
        final_success = bundle_success + move_success
        success_check = check_success(name_map, args.output_path)
        if final_success == 0 and success_check:
            print("Bundling and moving completed succesfully")
            if args.noclean==False:
                print(f"Removing {args.input_path}.")
                subprocess.run([f"rm -r {args.input_path}"], shell=True)
        else:
            print(f"Bundling and moving failed with error code {final_success}.")

        return final_success

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bundle and move MCwrapper outputs to another directory.")
    parser.add_argument("-f", action="store_true", help="Force overwrite of any potential existing output.")
    parser.add_argument("input_path", type=dir_path, help="The input path for directory to be merged.")
    parser.add_argument("output_path", type=dir_path, help="The output path for the merged directory.")
    parser.add_argument("-hddm", action="store_true", help="Use the Python hddm interfaces to merge hddm files instead of bundling with tar. Warning: may be very slow.")
    parser.add_argument("-noclean", action="store_true", help="Do not remove the input directory after a succesful merge.")
    args = parser.parse_args()
    sys.exit(main(args))
