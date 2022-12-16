import logging
import os
import time
from Moska.Game import MoskaGame
from Moska.Player.MoskaBot3 import MoskaBot3
from Moska.Player.AbstractPlayer import AbstractPlayer
from Moska.Player.HumanPlayer import HumanPlayer
import multiprocessing
from typing import Any, Callable, Dict, Iterable, List, Tuple
from Moska.Player.MoskaBot2 import MoskaBot2
from Moska.Player.RandomPlayer import RandomPlayer
from Moska.utils import add_before
import random
import numpy as np
from scipy.optimize import minimize
#from noisyopt import minimizeCompass,minimize

def set_game_args(game : MoskaGame, gamekwargs : Dict[str,Any]) -> None:
    """Sets a game instances variables from a dictionary of key-value pairs.
    If value is Callable, the returned value is assigned.

    Args:
        game (MoskaGame): The game whose attributes to set
        gamekwargs (Dict): _description_
    """
    for k,v in gamekwargs.items():
        if isinstance(v,Callable):
            v = v(game)
        game.__setattr__(k,v)
    return

def set_player_args(players : Iterable[AbstractPlayer], plkwargs : Dict[str,Any]) -> None:
    """Sets a player instances variables from a dictionary of key-value pairs.
    'players' must be an iterable, all of whose attributes are set to values found in 'plkwargs'
    If a value is Callable, the returned value is assigned.

    Args:
        players (Iterable[AbstractPlayer]): The players whose attributes will be set
        plkwargs (Dict[str,Any]): The attributes and corresponding values
    """
    for pl in players:
        for k,v in plkwargs.items():
            if isinstance(v,Callable):
                v = v(pl)
            pl.__setattr__(k,v)
    return

def set_player_args_optimize_bot3(players : Iterable[AbstractPlayer], plkwargs : Dict[str,Any],coeffs = {}):
    for pl in players:
        for k,v in plkwargs.items():
            if k == "coefficients" and not isinstance(pl,MoskaBot3):
                continue
            if isinstance(v,Callable):
                v = v(pl)
            pl.__setattr__(k,v)
    return

def args_to_game(
    game_kwargs : Callable,
    players : List[Tuple[AbstractPlayer,Callable]],
    gameid : int,
    shuffle : False,
    disable_logging : bool = False,
                        ):
    """Start a moska game with callable game arguments and players with callable arguments

    Args:
        game_kwargs (Callable): _description_
        players (List[Tuple[AbstractPlayer,Callable]]): _description_
        gameid (int): _description_
        shuffle (False): _description_

    Returns:
        _type_: _description_
    """
    game_args = game_kwargs(gameid)
    players = [pl(**args(gameid)) for pl, args in players]
    if disable_logging:
        set_player_args(players,{"log_file" : None})
        game_args["log_file"] = None
    if not players:
        assert "nplayers" in game_args or "players" in game_args
    else:
        game_args["players"] = players
    if shuffle and "players" in game_args:
        random.shuffle(game_args["players"])
    return game_args
    
def play_as_human():
    players = [
        (HumanPlayer,lambda x : {"name":"Human-","log_file":"human.log"}),
        (MoskaBot3,lambda x : {"log_file":"Bot3.log"}),
        (MoskaBot2,lambda x : {"log_file":"Bot2-log"}),
        (RandomPlayer,lambda x :{"log_file" : "Random1.log"})
               ]
    gamekwargs = lambda x : {
        "log_file" : "Humangame.log",
        "players" : players,
        "log_level" : logging.DEBUG,
        "timeout" : 320,
    }
    game = args_to_game(gamekwargs,players,0,True)
    return game.start()

def run_game(kwargs):
    return MoskaGame(**kwargs).start()

def play_games(players : List[Tuple[AbstractPlayer,Callable]],
               game_kwargs : Callable,
               n : int = 1,
               cpus :int = -1,
               chunksize : int = -1,
               shuffle_player_order = True,
               disable_logging = False,
               ):
    """ Simulate moska games with specified players. Return loss percent of each player.
    The players are specified by a list of tuples, with AbstractPlayer subclass and argument pairs.

    Args:
        players (List[Tuple[AbstractPlayer,Callable]]): The players are specified by a list of tuples, with (AbstractPlayer subclass, Callable -> dict) pairs.
        game_kwargs (Callable): A callable, that takes in the gameid, and returns the desired game arguments
        n (int, optional): Number of games to play. Defaults to 1.
        cpus (int, optional): Number of processes to start simultaneously. Defaults to the number of cpus.
        chunksize (int, optional): How many games to initially give each process. Defaults to defaults to n // cpus.
        shuffle_player_order (bool, optional) : Whether to randomly shuffle the player order in the game.

    Returns:
        Dict: _description_
    """
    start_time = time.time()
    # Select the specified number of cpus, or how many cpus are available
    cpus = min(os.cpu_count(),n) if cpus==-1 else cpus
    # Select the chunksize, so that it is close to 'chunksize * cpus = ngames'
    chunksize = n//cpus if chunksize == -1 else chunksize
    
    arg_gen = (args_to_game(game_kwargs,players,i,shuffle_player_order) for i in range(n))
    results = []
    print(f"Starting a pool with {cpus} processes and {chunksize} chunksize...")
    with multiprocessing.Pool(cpus) as pool:
        print("Games running...")
        gen = pool.imap_unordered(run_game,arg_gen,chunksize = chunksize)
        failed_games = 0
        while gen:
            try:
                res = next(gen)
            except StopIteration as si:
                break
            if res is None:
                failed_games += 1
                res = None
            #print(res)
            results.append(res)
    print(f"Simulated {len(results)} games. {len(results) - failed_games} succesful games. {failed_games} failed.")
    print(f"Time taken: {time.time() - start_time}")
    ranks = {}
    for res in results:
        if res is None:
            continue
        lastid = res[-1][0].split("-")[0]
        if lastid not in ranks:
            ranks[lastid] = 0
        ranks[lastid] += 1
    rank_list = list(ranks.items())
    rank_list.sort(key=lambda x : x[1])
    for pl,rank in rank_list:
        print(f"{pl} was last {round(100*rank/(len(results)-failed_games),2)} % times")
    return 100*(ranks["B3"]/len(results) - failed_games) if "B3" in ranks else 0

if __name__ == "__main__":
    n = 5
    if not os.path.isdir("Logs"):
        os.mkdir("Logs")
    os.chdir("Logs/")
    
    def to_minimize(params,**kwargs):
        coeffs = {
            "fall_card_already_played_value" : params[0],
            "fall_card_same_value_already_in_hand" : params[1],
             "fall_card_card_is_preventing_kopling" : params[2],
             "fall_card_deck_card_not_played_to_unique" : params[3],
             "fall_card_threshold_at_start" : params[4],
             "initial_play_quadratic_scaler" : params[5]
        }
        print("coeffs",coeffs)
        print("params",params)
        print("kwargs",kwargs)
        out = play_games(1600,5,log_prefix="moskafile",cpus=16,chunksize=5,coeffs=coeffs)
        print(f"Result: {out}")
        print("")
        return out
    #x0=[-0.1723, 0.31, -0.30, 0.39, 34.2, 0.35]
    #bounds = [(-1,0), (0,1), (-1,0), (0,1), (1,50), (0,1)]
    #res = minimize(to_minimize,x0=x0,method="powell",bounds=bounds)
    #print(f"Minimization result: {res}")
    players = [
        (MoskaBot3,lambda x : {"name" : f"Bot3-{x}-1-","log_file":f"Game-{x}-Bot3-1.log","log_level" : logging.DEBUG}),
        (MoskaBot3,lambda x : {"name" : f"Bot3-{x}-2-","log_file":f"Game-{x}-Bot3-2.log","log_level" : logging.DEBUG}),
        (MoskaBot2,lambda x : {"name" : f"Bot2-{x}-1-","log_file":f"Game-{x}-Bot2-1.log","log_level" : logging.DEBUG}),
        (MoskaBot2,lambda x : {"name" : f"Bot2-{x}-2-","log_file":f"Game-{x}-Bot2-2.log","log_level" : logging.DEBUG})
               ]
    gamekwargs = lambda x : {
        "log_file" : f"Game-{x}.log",
        "log_level" : logging.DEBUG,
        "timeout" : 1,
    }
    play_games(players, gamekwargs, n=100, cpus=16, chunksize=10,disable_logging=True)
    
    
    
    
    #play_as_human()
    
    
