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
import MySQLdb

dbhost = "hallddb.jlab.org"
dbuser = 'mcuser'
dbpass = ''
dbname = 'gluex_mc'

try:
    conn=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
    curs=conn.cursor(MySQLdb.cursors.DictCursor)
except:
    print("Could not connect to database")
    sys.exit(1)
    
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
    #check if the file .bash_root exists in the cwd directory.  IF it does skip the step and return 0
    print("Path: ", path)
    root_path=path.split("//")[0]
    print("Root path: ", root_path)
    if os.path.isfile(path.split("//")[0]+"/.bash_root"):
        print("Skipping bash_root step")
        return return_code
    
    checkpointpath = root_path + "/.checkpoints/root/"

    for dir_type in name_map.keys():
        print(f"Path: {path}    dir_type: {dir_type}")
        if not isinstance(dir_type,str):
            continue
        subprocess.run([f"mkdir -p {path + dir_type}"], shell=True)
        subprocess.run([f"mkdir -p {checkpointpath + dir_type}"], shell=True)
        if dir_type == "trees":
            for tup in name_map["trees"].keys():
                fold_name, suffix = tup[0], tup[1]
                fold_name = fold_name.rstrip("_")
                return_code += subprocess.run([f"mkdir {path + '/' + dir_type + '/' +  fold_name}"], shell=True).returncode
                return_code += subprocess.run([f"mkdir {checkpointpath + '/' + dir_type + '/' +  fold_name}"], shell=True).returncode
                for run in name_map["trees"][tup]["run_nums"]:
                    if os.path.isfile(checkpointpath + '/' + dir_type + '/' +  fold_name + '/' + tup[0] + run + tup[1] + '.done'):
                        continue
                    success = subprocess.run([f"/home/mcwrap/tools/hadd -v 1 -f {path + '/' + dir_type + '/' +  fold_name + '/' + tup[0] + run + tup[1]} {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    # success = subprocess.run([f"hadd -v 1 -f {path + '/' + dir_type + '/' +  fold_name + '/' + tup[0] + run + tup[1]} {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    return_code += success.returncode
                    if success.returncode == 0:
                        open(checkpointpath + '/' + dir_type + '/' +  fold_name + '/' + tup[0] + run + tup[1] + '.done', 'a').close()
                     #   good_runs.append(run)
        elif dir_type == "monitoring_hists":
            subprocess.run([f"mkdir -p {path + dir_type}"] , shell=True)
            subprocess.run([f"mkdir -p {checkpointpath + dir_type}"] , shell=True)
            for tup in name_map[dir_type].keys():
                for run in name_map[dir_type][tup]["run_nums"]:
                    if os.path.isfile(checkpointpath + '/' + dir_type + '/' +  tup[0] + run + tup[1] + '.tar.done'):
                        continue
                    success = subprocess.run([f"tar cvf {path + '/' + dir_type + '/' +  tup[0] + run + tup[1]}.tar {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    return_code += success.returncode
                    if success.returncode == 0:
                        open(checkpointpath + '/' + dir_type + '/' +  tup[0] + run + tup[1] + '.tar.done', 'a').close()
        else:
            subprocess.run([f"mkdir -p {path + dir_type}"] , shell=True)
            subprocess.run([f"mkdir -p {checkpointpath + dir_type}"] , shell=True)
            for tup in name_map[dir_type].keys():
                for run in name_map[dir_type][tup]["run_nums"]:
                    if os.path.isfile(checkpointpath + '/' + dir_type + '/' +  tup[0] + run + tup[1] + '.done'):
                        continue
                    success = subprocess.run([f"/home/mcwrap/tools/hadd -v 1 -f {path + '/' + dir_type + '/' +  tup[0] + run + tup[1]} {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    # success = subprocess.run([f"hadd -v 1 -f {path + '/' + dir_type + '/' +  tup[0] + run + tup[1]} {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    return_code += success.returncode
                    if success.returncode == 0:
                        open(checkpointpath + '/' + dir_type + '/' +  tup[0] + run + tup[1] + '.done', 'a').close()

    #if return_code=0 create empty file .bash_root in cwd directory
    if return_code==0:
        print("Creating .bash_root file in "+path)
        open(path.split("//")[0]+"/.bash_root", 'a').close()
    
    return return_code

@add_bash
def bash_hddm_merge(name_map, path, mc_dir):
    """Merge hddm files in mc_dir using the merge_hddm.py script."""
    return_code = 0

    if os.path.isfile(path + dir_type+"/.bash_hddm_merge"):
        print("Skipping bash_hddm_merge step")
        return return_code
    checkpointpath = path.split("//")[0] + "/.checkpoints/hddm/"

    MCWRAPPER_BOT_HOME="/scigroup/mcwrapper/gluex_MCwrapper/"
    subprocess.run([f"mkdir -p {path}"] , shell=True)
    subprocess.run([f"mkdir -p {checkpointpath}"] , shell=True)
    for tup in name_map.keys():
        for run in name_map[tup]["run_nums"]:
            print(f"hddm add {run}",flush=True)
            if os.path.isfile(checkpointpath + tup[0] + run + tup[1] + '.done'):
                continue
            success =  subprocess.run([f"python2 "+MCWRAPPER_BOT_HOME+f"/Utilities/merge_hddm.py {path + tup[0] + run + tup[1]} {mc_dir + '/hddm/' + tup[0] + run}*{tup[1]}"], shell=True)
            return_code += success.returncode
            if success.returncode == 0:
                open(checkpointpath + tup[0] + run + tup[1] + '.done', 'a').close()

    if return_code==0:
        print("Creating .bash_hddm_merge file in "+path)
        open(path + dir_type+"/.bash_hddm_merge", 'a').close()

    return return_code

@add_bash
def bash_hddm(name_map, path, mc_dir):
    """Bundle hddm files in mc_dir using tar."""
    return_code = 0
    if os.path.isfile(path.split("//")[0]+"/.bash_hddm"):
        print("Skipping bash_hddm step")
        return return_code

    checkpointpath = path.split("//")[0] + "/.checkpoints/hddm/"
    print("Checkpoint path: ", checkpointpath)

    subprocess.run([f"mkdir -p {path}"] , shell=True)
    subprocess.run([f"mkdir -p {checkpointpath}"] , shell=True)
    for tup in name_map.keys():
        for run in name_map[tup]["run_nums"]:
            if os.path.isfile(checkpointpath + tup[0] + run + tup[1] + '.tar.done'):
                continue
            success = subprocess.run([f"tar cvf {path + tup[0] + run + tup[1]}.tar {mc_dir + '/'  +  'hddm' + '/' +   tup[0] + run}_*{tup[1]}"], shell=True)
            return_code += success.returncode
            if success.returncode == 0:
                open(checkpointpath + tup[0] + run + tup[1] + '.tar.done', 'a').close()
    
    if return_code==0:
        print("Creating .bash_hddm file in "+path)
        open(path.split("//")[0]+"/.bash_hddm", 'a').close()


    return return_code


@add_bash
def bash_configurations(name_map, path, mc_dir):
    """Bundle config files in mc_dir."""
    return_code = 0
    if os.path.isfile(path.split("//")[0]+"/.bash_configurations"):
        print("Skipping bash_configurations step")
        return return_code

    checkpointpath = path.split("//")[0] + "/.checkpoints/configurations/"
    print("Checkpoint path: ", checkpointpath)

    for dir_type in name_map.keys():
        subprocess.run([f"mkdir -p {path + dir_type}"] , shell=True)
        subprocess.run([f"mkdir -p {checkpointpath + dir_type}"] , shell=True)
        for tup in name_map[dir_type].keys():
            for run in name_map[dir_type][tup]["run_nums"]:
                if os.path.isfile(checkpointpath + '/' + dir_type + '/' + tup[0] + run + tup[1] + '.tar.done'):
                    continue
                success = subprocess.run([f"tar cvf {path + '/' + dir_type + '/' + tup[0] + run + tup[1]}.tar {mc_dir + '/' + 'configurations' + '/' +  dir_type + '/' +   tup[0] + run}_*{tup[1]}"], shell=True)
                return_code += success.returncode
                if success.returncode == 0:
                    open(checkpointpath + '/' + dir_type + '/' + tup[0] + run + tup[1] + '.tar.done', 'a').close()
    
    if return_code==0:
        print("Creating .bash_configurations file in "+path)
        open(path.split("//")[0]+"/.bash_configurations", 'a').close()

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
        if type(k) is not str:
            print(f"{k} is not a string! Continue recurse_name_map...")
            continue
        if k=="hddm" and hddm==True:
            k = "hddm_merge"
        if ("bash_" + k) in bash.keys():
            dir_type = re.split("/", path)[-1]
            return_code = bash["bash_" + k](name_map[k], path+k+"/", mc_dir)
    return return_code



                
def bundle(name_map, mc_dir, temp_dir, hddm=False):
    """
    Traverse mc_dir via name_map and perform bash actions as appropriate.
    After all actions are complete, tar up the output.
    """

    return_code = 0
    if temp_dir is None:
        print("MC",mc_dir)
        return_code += subprocess.run([f"cd {mc_dir}; mkdir -p output"], shell=True).returncode
        return_code += subprocess.run([f"cd {mc_dir}; mkdir -p .checkpoints"], shell=True).returncode
    else:
        print("TEMP",temp_dir)
        return_code += subprocess.run([f"cd {temp_dir}; mkdir -p output"], shell=True).returncode
        return_code += subprocess.run([f"cd {temp_dir}; mkdir -p .checkpoints"], shell=True).returncode
    #else:
      #  return_code += subprocess.run([f"

    
    print("INITIAL BUNDLE STEP DONE")
    good_runs = []
    if temp_dir is None:
        bundle_success = recurse_name_map(name_map, f"{mc_dir + '/' + 'output/' }", mc_dir, hddm)
    else:
        bundle_success = recurse_name_map(name_map, f"{temp_dir + '/output/' }", mc_dir, hddm)
    return_code += bundle_success
    if temp_dir is None:
        return_code += subprocess.run([f"tar cvf {mc_dir + '/' +  'output.tar'} {mc_dir + '/' + 'output/' } --remove-files"], shell = True).returncode
    else:
        return_code += subprocess.run([f"tar cvf {temp_dir + '/' + 'output.tar'} {temp_dir + '/output/'} --remove-files"], shell = True).returncode
    return return_code
   
def move(mc_dir, temp_dir, out_dir):
    """
    Move the bundled up mc_dir into out_dir and remove the temporary output
    from mc_dir.
    """
    n_strip_components = mc_dir.strip(os.sep).count(os.sep) + 2
    if temp_dir is None:
        success = subprocess.run([f"mv {mc_dir + '/' + 'output.tar' } {out_dir}; cd {out_dir}; tar xvf output.tar --strip-components={n_strip_components}; rm output.tar"], shell=True)
    else:
        success = subprocess.run([f"mv {temp_dir + '/' + 'output.tar' } {out_dir}; cd {out_dir}; tar xvf output.tar --strip-components={n_strip_components}; rm output.tar"], shell=True)
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
    #only count non hidden files
    merged_file_no = sum([len([f for f in files if not f.startswith(".")]) for r, d, files in os.walk(output_path)])
    #merged_file_no = sum([len(files) for r, d, files in os.walk(output_path)])
    print(f"Number of unique files output is {merged_file_no}")

    return mc_file_no == merged_file_no

def main(args):

    if args.tempdir is None:
        if os.path.isfile(args.output_path+"/.merging"):
            print("Merging already in progress.  Exiting.")
            return -666
        print("Creating .merging file")
        open(args.output_path+"/.merging", 'a').close()
    else:
        print("Tempdir: ", args.tempdir)
        if os.path.isfile(args.tempdir+"/.merging"):
            print("Merging already in progress.  Exiting.")
            return -666
        print("Creating .merging file")
        open(args.tempdir+"/.merging", 'a').close()
    

    print("args: ", args)

    input_path = args.input_path
    output_path = args.output_path

    if args.P:
        curs.execute("SELECT * FROM Project WHERE ID=%s",args.P)
        proj=curs.fetchone()
        input_path= proj["OutputLocation"].replace("/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/","/work/halld/gluex_simulations/REQUESTED_MC/")
        output_path="/".join(proj["OutputLocation"].split("/")[:-1])+"/"


    print(f"Moving from: {args.input_path} to {args.output_path}")
    if args.f==False:
        
        if args.tempdir is None:
            searchpath = args.input_path
        else:
            searchpath = args.tempdir

        for path, dirs, files in os.walk(searchpath):
            if "output" in dirs:
                print("The directory in the input path might already be in the process of bundling. Use the -f flag to clear out and start fresh.")
                for path, dirs, files in os.walk(args.output_path):
                    for existing_dir in ["configurations", "root", "hddm"]:
                        if existing_dir in dirs:
                            print("Output path might already contain bundled files. Use the -f flag to clear out and start fresh.")
                            return -1
    print("INPUT:",args.input_path)
    name_map = get_directory_structure(args.input_path)
    dir_type = re.split("/", args.input_path.rstrip(os.sep))[-1]
    print("===================================")
    print(name_map)
    print("dir_type",dir_type)

    print(name_map.keys())
    bundle_success = bundle(name_map[dir_type], args.input_path.rstrip(os.sep), args.tempdir, args.hddm)
    move_success = move(args.input_path, args.tempdir, args.output_path)
    final_success = bundle_success + move_success
    success_check = check_success(name_map, args.output_path)

    print(f"bundle_success: {bundle_success}, move_success: {move_success}, final_success: {final_success}, success_check: {success_check}")

    if final_success == 0 and success_check:
        print("Bundling and moving completed succesfully")

        if args.noclean==False:
            print(f"Removing {args.input_path}.")
            subprocess.run([f"rm -r {args.input_path}"], shell=True)
    else:
        print(f"Bundling and moving failed with error code {final_success}.")

    print(f"Returning final_success: {final_success}")
    return final_success

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bundle and move MCwrapper outputs to another directory.")
    parser.add_argument("-f", action="store_true", help="Force overwrite of any potential existing output.")
    parser.add_argument("input_path", type=dir_path, help="The input path for directory to be merged.")
    parser.add_argument("output_path", type=dir_path, help="The output path for the merged directory.")
    parser.add_argument("-hddm", action="store_true", help="Use the Python hddm interfaces to merge hddm files instead of bundling with tar. Warning: may be very slow.")
    parser.add_argument("-noclean", action="store_true", help="Do not remove the input directory after a succesful merge.")
    parser.add_argument("-tempdir", type=dir_path, help="Specify a temporary directory in which the bundling will take place.")
    parser.add_argument("-P",help="ID number of the project to bundle.")
    args = parser.parse_args()
    sys.exit(main(args))
