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
import glob
import json
import tempfile
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


def check_root_merge(output, files):
    """Compare entries in every output tree with the sum of its input trees."""
    macro = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_root_merge.C")
    with tempfile.NamedTemporaryFile(mode="w") as file_list:
        file_list.write("\n".join(files) + "\n")
        file_list.flush()
        return subprocess.run(["root", "-l", "-b", "-q",
                               macro + "(" + json.dumps(output) + "," + json.dumps(file_list.name) + ")"]).returncode


def merge_root(output, pattern, checkpoint):
    files = sorted(glob.glob(pattern))
    if not files:
        print("No ROOT inputs match " + pattern)
        return 1
    if os.path.isfile(checkpoint) and os.path.isfile(output):
        if check_root_merge(output, files) == 0:
            return 0
    if subprocess.run(["rm", "-f", checkpoint]).returncode != 0:
        return 1
    with tempfile.NamedTemporaryFile(mode="w") as file_list:
        file_list.write("\n".join(files) + "\n")
        file_list.flush()
        success = subprocess.run(["hadd", "-v", "1", "-f", output, "@" + file_list.name])
    if success.returncode != 0:
        return success.returncode
    return check_root_merge(output, files)


@add_bash
def bash_root(name_map, path, mc_dir):
    """Merge root files in mc_dir."""
    return_code = 0
    print("Path: ", path)
    root_path=path.split("//")[0]
    print("Root path: ", root_path)

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
                return_code += subprocess.run([f"mkdir -p {path + '/' + dir_type + '/' +  fold_name}"], shell=True).returncode
                return_code += subprocess.run([f"mkdir -p {checkpointpath + '/' + dir_type + '/' +  fold_name}"], shell=True).returncode
                for run in name_map["trees"][tup]["run_nums"]:
                    # success = subprocess.run([f"/home/mcwrap/tools/hadd -v 1 -f {path + '/' + dir_type + '/' +  fold_name + '/' + tup[0] + run + tup[1]} {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    success = merge_root(path + '/' + dir_type + '/' + fold_name + '/' + tup[0] + run + tup[1],
                                         mc_dir + '/root/' + dir_type + '/' + tup[0] + run + '*' + tup[1],
                                         checkpointpath + '/' + dir_type + '/' + fold_name + '/' + tup[0] + run + tup[1] + '.done')
                    # success = subprocess.run([f"/home/mcwrap/sw/root-6.32.20-gcc11.5.0/bin/hadd -v 1 -f {path + '/' + dir_type + '/' +  fold_name + '/' + tup[0] + run + tup[1]} {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    if success != 0:
                        return success
                    open(checkpointpath + '/' + dir_type + '/' +  fold_name + '/' + tup[0] + run + tup[1] + '.done', 'a').close()
                     #   good_runs.append(run)
        elif dir_type == "monitoring_hists":
            subprocess.run([f"mkdir -p {path + dir_type}"] , shell=True)
            subprocess.run([f"mkdir -p {checkpointpath + dir_type}"] , shell=True)
            for tup in name_map[dir_type].keys():
                for run in name_map[dir_type][tup]["run_nums"]:
                    success = subprocess.run([f"tar cvf {path + '/' + dir_type + '/' +  tup[0] + run + tup[1]}.tar {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    return_code += success.returncode
                    if success.returncode == 0:
                        open(checkpointpath + '/' + dir_type + '/' +  tup[0] + run + tup[1] + '.tar.done', 'a').close()
        else:
            subprocess.run([f"mkdir -p {path + dir_type}"] , shell=True)
            subprocess.run([f"mkdir -p {checkpointpath + dir_type}"] , shell=True)
            for tup in name_map[dir_type].keys():
                for run in name_map[dir_type][tup]["run_nums"]:
                    # success = subprocess.run([f"/home/mcwrap/tools/hadd -v 1 -f {path + '/' + dir_type + '/' +  tup[0] + run + tup[1]} {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    success = merge_root(path + '/' + dir_type + '/' + tup[0] + run + tup[1],
                                         mc_dir + '/root/' + dir_type + '/' + tup[0] + run + '*' + tup[1],
                                         checkpointpath + '/' + dir_type + '/' + tup[0] + run + tup[1] + '.done')
                    # success = subprocess.run([f"/home/mcwrap/sw/root-6.32.20-gcc11.5.0/bin/hadd -v 1 -f {path + '/' + dir_type + '/' +  tup[0] + run + tup[1]} {mc_dir + '/' + 'root' + '/' +  dir_type + '/' + tup[0]+run}*{tup[1]}"], shell=True)
                    if success != 0:
                        return success
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

    checkpointpath = path.split("//")[0] + "/.checkpoints/hddm/"

    MCWRAPPER_BOT_HOME="/scigroup/mcwrapper/gluex_MCwrapper/"
    subprocess.run([f"mkdir -p {path}"] , shell=True)
    subprocess.run([f"mkdir -p {checkpointpath}"] , shell=True)
    for tup in name_map.keys():
        for run in name_map[tup]["run_nums"]:
            print(f"hddm add {run}",flush=True)
            output = path + tup[0] + run + tup[1]
            files = sorted(glob.glob(mc_dir + '/hddm/' + tup[0] + run + '*' + tup[1]))
            if not files:
                return 1
            command = ["python2", MCWRAPPER_BOT_HOME + "/Utilities/merge_hddm.py", output] + files
            if subprocess.run(["rm", "-f", checkpointpath + tup[0] + run + tup[1] + '.done']).returncode != 0:
                return 1
            success = subprocess.run(command)
            if success.returncode != 0:
                return success.returncode
            open(checkpointpath + tup[0] + run + tup[1] + '.done', 'a').close()

    if return_code==0:
        print("Creating .bash_hddm_merge file in "+path)
        open(path.split("//")[0]+"/.bash_hddm_merge", 'a').close()

    return return_code


@add_bash
def bash_hddm(name_map, path, mc_dir):
    """Bundle hddm files in mc_dir using tar."""
    return_code = 0

    checkpointpath = path.split("//")[0] + "/.checkpoints/hddm/"
    print("Checkpoint path: ", checkpointpath)

    subprocess.run([f"mkdir -p {path}"] , shell=True)
    subprocess.run([f"mkdir -p {checkpointpath}"] , shell=True)
    for tup in name_map.keys():
        for run in name_map[tup]["run_nums"]:
            #success = subprocess.run([f"tar cvf {path + tup[0] + run + tup[1]}.tar {mc_dir + '/'  +  'hddm' + '/' +   tup[0] + run}_*{tup[1]}"], shell=True)
            
            file_list=[]
            pattern = re.compile(rf"^{re.escape(tup[0])}{re.escape(run)}_(\d{{3,4}}){re.escape(tup[1])}$")
            for fname in os.listdir(mc_dir + '/hddm/'):
                match = pattern.match(fname)
                if match:
                    file_list.append(fname)
            if len(file_list) < 1:
                return 1
            
            bundle_command=f"tar cvf {path + tup[0] + run + tup[1]}.tar"
            for fname in file_list:
                bundle_command = bundle_command + f" {mc_dir}/hddm/{fname}"
            #print(bundle_command)
            
            success = subprocess.run(bundle_command, shell=True)
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

    checkpointpath = path.split("//")[0] + "/.checkpoints/configurations/"
    print("Checkpoint path: ", checkpointpath)

    for dir_type in name_map.keys():
        subprocess.run([f"mkdir -p {path + dir_type}"] , shell=True)
        subprocess.run([f"mkdir -p {checkpointpath + dir_type}"] , shell=True)
        for tup in name_map[dir_type].keys():
            for run in name_map[dir_type][tup]["run_nums"]:
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
    match = re.search("([0-9]{6})_([0-9]{3,4})(?![0-9])", file_name)
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
        action = "bash_hddm_merge" if k=="hddm" and hddm==True else "bash_" + k
        if action in bash.keys():
            dir_type = re.split("/", path)[-1]
            success = bash[action](name_map[k], path+k+"/", mc_dir)
            if success != 0:
                return success
    return return_code


def bundle(name_map, mc_dir, temp_dir, hddm=False):
    """Bundle outputs into the staging directory."""

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
        bundle_success = recurse_name_map(name_map, mc_dir.rstrip(os.sep) + "//output/", mc_dir, hddm)
    else:
        bundle_success = recurse_name_map(name_map, temp_dir.rstrip(os.sep) + "//output/", mc_dir, hddm)
    if bundle_success != 0:
        return bundle_success
    return return_code


def move(mc_dir, temp_dir, out_dir):
    """Publish the output directory on the same filesystem."""
    source = os.path.join(temp_dir if temp_dir is not None else mc_dir, "output")
    out_dir = out_dir.rstrip(os.sep)
    destination = out_dir if os.path.exists(out_dir) else os.path.dirname(os.path.abspath(out_dir))
    if os.stat(source).st_dev != os.stat(destination).st_dev:
        print("Staging and destination must be on the same filesystem; keeping staged files.")
        return 1
    if os.path.exists(out_dir) and os.listdir(out_dir):
        print("Destination already contains files; keeping staged files.")
        return 1
    identity = os.stat(source)
    success = subprocess.run(["mv", "-T", source, out_dir])
    if success.returncode == 0:
        published = os.stat(out_dir)
        if (identity.st_dev, identity.st_ino) != (published.st_dev, published.st_ino):
            return 1
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

    return mc_file_no > 0 and mc_file_no == merged_file_no


def main(args):
    if args.P:
        curs.execute("SELECT * FROM Project WHERE ID=%s",args.P)
        proj=curs.fetchone()
        args.input_path = proj["OutputLocation"].replace("/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/","/work/halld/gluex_simulations/REQUESTED_MC/")
        args.output_path = "/".join(proj["OutputLocation"].split("/")[:-1])+"/"

    if args.tempdir is None:
        args.tempdir = args.output_path.rstrip(os.sep) + ".mergetemp/"
    args.tempdir = os.path.normpath(args.tempdir)
    if subprocess.run(["mkdir", "-p", args.tempdir]).returncode != 0:
        return 1
    lockfile = os.path.join(args.tempdir, ".merging")
    try:
        open(lockfile, 'x').close()
    except FileExistsError:
        print("Merging already in progress.  Exiting.")
        # EX_TEMPFAIL: merge already running.
        return 75
    try:
        return bundle_project(args)
    finally:
        subprocess.run(["rm", "-f", lockfile])


def input_snapshot(path):
    files = {}
    for directory, dirs, names in os.walk(path):
        for name in names:
            filename = os.path.join(directory, name)
            info = os.stat(filename)
            files[filename] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime)
    return files


def bundle_project(args):
    print("args: ", args)
    print(f"Moving from: {args.input_path} to {args.output_path}")
    input_path = os.path.realpath(args.input_path)
    for path in (args.tempdir, args.output_path):
        path = os.path.realpath(path)
        if path == input_path or path.startswith(input_path + os.sep) or input_path.startswith(path + os.sep):
            print("Input, staging, and destination must be separate directories.")
            return 1
    original_files = input_snapshot(args.input_path)
    print("INPUT:",args.input_path)
    name_map = get_directory_structure(args.input_path)
    dir_type = re.split("/", args.input_path.rstrip(os.sep))[-1]
    print("===================================")
    print(name_map)
    print("dir_type",dir_type)

    print(name_map.keys())
    bundle_success = bundle(name_map[dir_type], args.input_path.rstrip(os.sep), args.tempdir, args.hddm)
    if bundle_success != 0:
        print(f"Bundling failed with error code {bundle_success}; keeping inputs and staged files.")
        return 2
    staged_output = os.path.join(args.tempdir, "output")
    if not check_success(name_map, staged_output) or original_files != input_snapshot(args.input_path):
        print("Staged output validation failed or inputs changed; keeping inputs and staged files.")
        return 3
    move_success = move(args.input_path, args.tempdir, args.output_path)
    if move_success != 0:
        print(f"Publishing failed with error code {move_success}; keeping inputs and staged files.")
        return 4
    if not check_success(name_map, args.output_path) or original_files != input_snapshot(args.input_path):
        print("Published output validation failed or inputs changed; keeping inputs.")
        return 3
    print("Bundling and moving completed succesfully")
    if args.noclean==False:
        print(f"Removing {args.input_path}.")
        return subprocess.run(["rm", "-r", args.input_path]).returncode
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bundle and move MCwrapper outputs to another directory.")
    parser.add_argument("-f", action="store_true", help="Legacy option; published output is never overwritten.")
    parser.add_argument("input_path", type=dir_path, help="The input path for directory to be merged.")
    parser.add_argument("output_path", type=dir_path, help="The output path for the merged directory.")
    parser.add_argument("-hddm", action="store_true", help="Use the Python hddm interfaces to merge hddm files instead of bundling with tar. Warning: may be very slow.")
    parser.add_argument("-noclean", action="store_true", help="Do not remove the input directory after a succesful merge.")
    parser.add_argument("-tempdir", type=dir_path, help="Specify a temporary directory in which the bundling will take place.")
    parser.add_argument("-P",help="ID number of the project to bundle.")
    args = parser.parse_args()
    sys.exit(main(args))
