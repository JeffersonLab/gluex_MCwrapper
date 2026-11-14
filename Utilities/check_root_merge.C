#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <string>

#include "TClass.h"
#include "TDirectory.h"
#include "TFile.h"
#include "TKey.h"
#include "TSystem.h"
#include "TTree.h"

// Read tree headers only.
void tree_entries(TDirectory *directory, const std::string &prefix,
                  std::map<std::string, Long64_t> &entries)
{
    if (!directory)
        gSystem->Exit(1);
    std::set<std::string> seen;
    TIter next(directory->GetListOfKeys());
    while (TKey *key = static_cast<TKey *>(next())) {
        if (!seen.insert(key->GetName()).second)
            continue;
        TClass *type = TClass::GetClass(key->GetClassName());
        if (!type)
            continue;
        std::string path = prefix + key->GetName();
        if (type->InheritsFrom(TDirectory::Class())) {
            tree_entries(directory->GetDirectory(key->GetName()), path + "/", entries);
        } else if (type->InheritsFrom(TTree::Class())) {
            TTree *tree = nullptr;
            directory->GetObject(key->GetName(), tree);
            if (!tree)
                gSystem->Exit(1);
            entries[path] += tree->GetEntries();
        }
    }
}

bool file_entries(const char *filename, std::map<std::string, Long64_t> &entries)
{
    TFile file(filename, "READ");
    if (file.IsZombie())
        return false;
    tree_entries(&file, "", entries);
    return true;
}

void check_root_merge(const char *output, const char *input_list)
{
    std::map<std::string, Long64_t> expected, actual;
    std::ifstream inputs(input_list);
    std::string filename;
    bool have_inputs = false;
    while (std::getline(inputs, filename)) {
        have_inputs = true;
        if (!file_entries(filename.c_str(), expected))
            gSystem->Exit(1);
    }
    if (!have_inputs || !file_entries(output, actual))
        gSystem->Exit(1);
    if (expected != actual) {
        std::cerr << "Tree entry counts do not match for " << output << std::endl;
        for (const auto &entry : expected)
            std::cerr << entry.first << ": expected " << entry.second
                      << ", got " << actual[entry.first] << std::endl;
        gSystem->Exit(1);
    }
    std::cout << "Tree entry counts match for " << output << std::endl;
    gSystem->Exit(0);
}
