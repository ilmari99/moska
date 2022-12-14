#!/usr/bin/env python3
import os
import random
import re
import pandas as pd
import tensorflow as tf

def create_tf_dataset(paths, add_channel=False) -> tf.data.Dataset:
    """ Create a tf dataset from a folder of files"""
    if not isinstance(paths, (list, tuple)):
        try:
            paths = [paths]
        except:
            raise ValueError("Paths should must be a list of strings")
    file_paths = []
    for path in paths:
        if not os.path.isdir(path):
            raise ValueError(f"Path {path} is not a directory")
        file_paths += [os.path.join(path, file) for file in os.listdir(path)]
    print("Number of files: " + str(len(file_paths)))
    random.shuffle(file_paths)
    print("Shuffled files.")
    print(file_paths[0:10])
    dataset = tf.data.TextLineDataset(file_paths)
    dataset = dataset.map(lambda x: tf.strings.split(x, sep=", "))
    dataset = dataset.map(lambda x: (tf.strings.to_number(x[:-1]), tf.strings.to_number(x[-1])))
    if add_channel:
        dataset = dataset.map(lambda x,y: (tf.expand_dims(x, axis=-1), tf.expand_dims(y, axis=-1)))
    return dataset
    
    

def check_unique_vectors(path):
    """ Check that there are no duplicate lines in files in path"""
    with open(path,"r") as f:
        lines = f.readlines()
        uniq_lines = set(lines)
        print(f"Number of unique lines: {len(uniq_lines)}")
    print("Number of lines: " + str(len(lines)))
    print("Percent unique data: " + str(len(uniq_lines)/len(lines)))


def check_line_lengths_equal(path):
    line_length = -1
    out = True
    nlines = 0
    nlosses = 0
    for file in os.listdir(path):
        with open(path+file,"r") as f:
            for line in f:
                nlines += 1
                if line_length == -1:
                    line_length = line.count(",")
                    print("Line length: " + str(line_length))
                line = line.strip()
                if line[-1] == "0":
                    nlosses += 1
                if line.count(",") != line_length:
                    print(f"Line length mismatch in {file}")
                    out = False
                    break
    if out:
        print(f"All {nlines} lines are the same length")
    print(f"Loss ratio: {nlosses/nlines}")
    return out

def get_n_losses(path):
    """ Get the distribution of winners/losses in the file"""
    with open(path,"r") as f:
        n_losses = 0
        data_length = 0
        for line in f:
            data_length += 1
            line = line.strip()
            if line[-1] == "0":
                n_losses += 1
        print(f"{path} : {n_losses}")
        print(f"Data length: {data_length}")
        print(f"Loss ratio: {n_losses/data_length}")


def combine_files(path,output="combined.csv"):
    """ Combine all files in path into one file"""
    with open(output,"w") as f:
        for file in os.listdir(path):
            with open(path+file,"r") as f2:
                for line in f2:
                    f.write(line)
            f.write("\n")
            
def to_single_dataset(path,pickle_file="data.pkl"):
    """ Convert a bunch of files to an hdf5 file.
    Shuffle and balance the data and save it.
    """
    data = pd.read_csv(path)
    winners = data[data.iloc[:,-1] == 1]
    losers = data[data.iloc[:,-1] == 0]
    winners = winners.sample(n=losers.shape[0])
    print(f"Winners: {winners.shape}")
    print(f"Losers: {losers.shape}")
    data = pd.concat([winners, losers],axis=0,ignore_index=True)
    data = data.sample(frac=1).reset_index(drop=True)
    data.to_pickle(pickle_file)
    print(f"Saved data to '{pickle_file}'")
    print(data.head())
    print(data.describe())

def balance_data(path):
    """ Balance the data by removing the extra 1s"""
    ftype = path.split(".")[-1]
    fname = path.split(".")[0]
    if ftype == "csv":
        data = pd.read_csv(path)
        data.to_pickle(fname +".pkl")
        print(f"Converted {path} to pkl")
    elif ftype == "pkl":
        data = pd.read_pickle(path)
    winners = data[data.iloc[:,-1] == 1]
    losers = data[data.iloc[:,-1] == 0]
    winners = winners.sample(n=losers.shape[0])
    print(f"Winners: {winners.shape}")
    print(f"Losers: {losers.shape}")
    data = pd.concat([winners, losers],axis=0)
    data = data.sample(frac=1).reset_index(drop=True)
    data.to_pickle(f"balanced-{fname}.pkl")
    print(f"Saved data to 'balanced-{fname}.pkl'")
    print(data.head())
    print(data.describe())
    
def find_duplicate_files(remove=False):
    folder_one = "./MB1Logs/Logs/Vectors/"
    folder_two = "./Logs/Vectors/"
    files_in_one = set(os.listdir(folder_one))
    files_in_two = set(os.listdir(folder_two))
    duplicate_files = files_in_one.intersection(files_in_two)
    print(f"Number of duplicate files: {len(duplicate_files)}")
    if not remove:
        return
    count = 0
    for i,file in enumerate(duplicate_files):
        os.remove(folder_two + file)
        if i % 100 == 0:
            print(f"{i/len(duplicate_files)*100}% complete")
    return

if __name__ == "__main__":
    CWD = os.getcwd()
    PATH = "./Data/MB1Logs168k/Logs/Vectors/"
    print("Current working directory: " + CWD)
    #find_duplicate_files()
    #balance_data()
    check_line_lengths_equal(PATH)
    #combine_files(PATH,output="combined.csv")
    #get_n_losses("combined.csv")
    #check_unique_vectors("combined.csv")

