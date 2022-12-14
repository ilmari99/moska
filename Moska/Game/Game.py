import contextlib
import copy
import os
import tensorflow as tf
from Moska.Game.GameState import GameState
from ..Player.MoskaBot3 import MoskaBot3
from . import utils
from ..Player.MoskaBot0 import MoskaBot0
from ..Player.AbstractPlayer import AbstractPlayer
from ..Player.MoskaBot1 import MoskaBot1
from ..Player.MoskaBot2 import MoskaBot2
from ..Player.RandomPlayer import RandomPlayer
import numpy as np
from typing import Any, Callable, Dict, List, Tuple
from .Deck import Card, StandardDeck
from .CardMonitor import CardMonitor
import threading
import logging
import random
#import tensorflow as tf
from .Turns import PlayFallFromDeck, PlayFallFromHand, PlayToOther, InitialPlay, EndTurn, PlayToSelf, Skip, PlayToSelfFromDeck


class MoskaGame:
    players : List[AbstractPlayer] = [] # List of players, with unique pids, and cards already in hand
    triumph : str = ""              # Triumph suit, set when the moskaGame is started
    triumph_card : Card = None             # Triumph card
    cards_to_fall : List[Card] = []              # Current cards on the table, for the target to fall
    fell_cards : List[Card] = []                 # Cards that have fell during the last turn
    turnCycle = utils.TurnCycle([],ptr = 0) # A TurnCycle instance, that rotates from the last to the first, created when players defined
    deck  : StandardDeck = None                             # The deck belonging to the moskaGame. 
    threads : Dict[int,AbstractPlayer] = {}
    log_file : str = ""
    log_level = logging.INFO
    name : str = __name__
    glog : logging.Logger = None
    main_lock : threading.RLock = None
    lock_holder = None
    turns : dict = {}
    timeout : float = 3
    random_seed = None
    nplayers : int = 0
    card_monitor : CardMonitor = None
    EXIT_FLAG = False
    def __init__(self,
                 deck : StandardDeck = None,
                 players : List[AbstractPlayer] = [],
                 nplayers : int = 0,
                 log_file : str = "",
                 log_level = logging.INFO,
                 timeout=3,
                 random_seed=None
                 ):
        """Create a MoskaGame -instance.

        Args:
            deck (StandardDeck): The deck instance, from which to draw cards.
        """
        self.interpreter = tf.lite.Interpreter(model_path="/home/ilmari/python/moska/ModelMB2/model.tflite",)
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        #print(self.input_details)
        self.threads = {}
        if self.players or self.nplayers > 0:
            print("LEFTOVER PLAYERS FOUND!!!!!!!!!!!!!")
        if self.card_monitor is not None:
            print("LEFOVER card_monitor!!!!!!!!!!!!1")
        if self.threads:
            print("LEFTOVER THREAD!!!!!")
        self.log_level = log_level
        self.log_file = log_file if log_file else os.devnull
        self.random_seed = random_seed if random_seed else int(100000*random.random())
        self.deck = deck if deck else StandardDeck(seed = self.random_seed)
        self.players = players if players else self._get_random_players(nplayers)
        self.timeout = timeout
        self.EXIT_FLAG = False
        self.card_monitor = CardMonitor(self)
        self._set_turns()
        #self.model = tf.keras.models.load_model("/home/ilmari/python/moska/Model5-300/model.h5")
    
    def model_predict(self, X):
        self.threads[threading.get_native_id()].plog.debug(f"Predicting with model, X.shape = {X.shape}")
        self.interpreter.resize_tensor_input(self.input_details[0]["index"],X.shape)
        self.interpreter.allocate_tensors()
        self.interpreter.set_tensor(self.input_details[0]['index'], X)
        self.interpreter.invoke()
        output_data = self.interpreter.get_tensor(self.output_details[0]['index'])
        return output_data
    
    def _set_turns(self):
        self.turns = {
        "PlayFallFromHand" : PlayFallFromHand(self),
        "PlayFallFromDeck" : PlayFallFromDeck(self),
        "PlayToOther" : PlayToOther(self),
        "PlayToSelf" : PlayToSelf(self),
        "InitialPlay" : InitialPlay(self),
        "EndTurn": EndTurn(self),
        "Skip":Skip(self),
        "PlayToSelfFromDeck":PlayToSelfFromDeck(self)
        }
        return


    def __getattribute____(self, __name: str) -> Any:
        """ This is a fail safe to prevent dangerous access to MoskaGame
        attributes from outside the main or player threads, when the game is locked.
        """
        non_accessable_attributes = ["card_monitor", "deck", "turnCycle", "cards_to_fall", "fell_cards", "players"]
        if __name in non_accessable_attributes and self.threads and threading.get_native_id() != self.lock_holder:
            raise threading.ThreadError(f"Getting MoskaGame attribute with out lock!")
        return object.__getattribute__(self,__name)
    
    def __setattr__(self, name, value):
        """ Prevent access to MoskaGame attributes from outside the main or player threads, when the game is locked.
        Also used for ensuring that inter-related attributes are set correctly.
        """
        if name != "lock_holder" and self.threads and threading.get_native_id() != self.lock_holder:
            raise threading.ThreadError(f"Setting MoskaGame attribute with out lock!")
        super.__setattr__(self, name, value)
        # If setting the players, set the turnCycle and the new deck
        if name == "players":
            self._set_players(value)
            self.glog.debug(f"Set players to: {value}")
        # If setting the log_file, set the logger
        if name == "log_file" and value:
            assert isinstance(value, str), f"'{name}' of MoskaGame attribute must be a string"
            self.name = value.split(".")[0]
            self._set_glogger(value)
            self.glog.debug(f"Set GameLogger (glog) to file {value}")
        # If setting nplayers, create random players and set self.players
        if name == "nplayers":
            self.players = self.players if self.players else self._get_random_players(value)
            self.glog.debug(f"Created {value} random players.")
        # If setting the random seed, set the random seed
        if name == "random_seed":
            random.seed(value)     
            self.glog.info(f"Set random_seed to {self.random_seed}")
        return
    
    def _set_players(self,players : List[AbstractPlayer]) -> None:
        """Here self.players is already set to players
        """
        assert isinstance(players, list), f"'players' of MoskaGame attribute must be a list"
        self.deck = StandardDeck(seed=self.random_seed)
        for pl in players:
            pl.moskaGame = self
        self.turnCycle = utils.TurnCycle(players)
        return
        
    @classmethod
    def _get_random_players(cls,n, player_types : List[Callable] = [],**plkwargs) -> List[AbstractPlayer]:
        """ Get a list of AbstractPlayer  subclasses.
        The players will be dealt cards from a new_deck if called from an instance.

        Args:
            n (int): Number of players to create
            player_types (list[Callable], optional): The player types to use. Defaults to all.

        Returns:
            _type_: _description_
        """
        players = []
        if not player_types:
            player_types = [MoskaBot0,MoskaBot1, MoskaBot2, MoskaBot3, RandomPlayer]
        for i in range(n):
            rand_int = random.randint(0, len(player_types)-1)
            player = player_types[rand_int]()
            players.append(player)
        return players
    
    def _set_glogger(self,log_file : str) -> None:
        """Set the games logger `glog`.

        Args:
            log_file (str): Where to write the games log
        """
        self.glog = logging.getLogger(self.name)
        self.glog.setLevel(self.log_level)
        fh = logging.FileHandler(log_file,mode="w",encoding="utf-8")
        formatter = logging.Formatter("%(name)s:%(levelname)s:%(message)s")
        fh.setFormatter(formatter)
        self.glog.addHandler(fh)
        return
    
    def _create_locks(self) -> None:
        """ Initialize the RLock for the game. """
        self.main_lock = threading.RLock()
        self.glog.debug("Created RLock")
        return
    
    @contextlib.contextmanager
    def get_lock(self,player=None):
        """A wrapper around getting the moskagames main_lock.
        Sets the lock_holder to the obtaining threads id

        Args:
            player (_type_): _description_

        Yields:
            _type_: _description_
        """
        with self.main_lock as lock:
            self.lock_holder = threading.get_native_id()
            og_state = len(self.cards_to_fall + self.fell_cards)
            if self.lock_holder not in self.threads:
                self.lock_holder = None
                print(f"Game {self.log_file}: Couldn't find lock holder id {self.lock_holder}!")
                yield False
                return
            if self.EXIT_FLAG:
                self.lock_holder = None
                yield False
                return
            # Here we tell the player that they have the key
            yield True
            state = len(self.cards_to_fall + self.fell_cards)
            if og_state != state:
                self.glog.info(f"{self.threads[self.lock_holder].name}: new board: {self.cards_to_fall}")
            assert len(set(self.cards_to_fall)) == len(self.cards_to_fall), f"Game log {self.log_file} failed, DUPLICATE CARD"
            pl = self.threads[self.lock_holder]
            if False and isinstance(pl, AbstractPlayer):
                inp = pl.state_vectors[-1]
                #print(inp)
                possib_to_not_lose = self.model.predict(np.array([inp]),verbose=0)
                print(f"{pl.name} has {possib_to_not_lose[0]} chance of not losing")
            self.lock_holder = None
        return
    
    def _make_move(self,move,args) -> Tuple[bool,str]:
        """ This is called from a AbstractPlayer -instance
        """
        if self.lock_holder != threading.get_native_id():
            raise threading.ThreadError(f"Making moves is supposed to be implicit and called in a context manager after acquiring the games lock")
        if move not in self.turns.keys():
            raise NameError(f"Attempted to make move '{move}' which is not recognized as a move in Turns.py")
        move_call = self.turns[move]
        self.glog.debug(f"Player {self.threads[self.lock_holder].name} called {move} with args {args}")
        try:
            move_call(*args)  # Calls a class from Turns, which raises AssertionError if the move is not playable
        except AssertionError as ae:
            self.glog.warning(f"{self.threads[threading.get_native_id()].name}:{ae}")
            return False, str(ae)
        except TypeError as te:
            self.glog.warning(f"{self.threads[threading.get_native_id()].name}:{te}")
            return False, str(te)
        self.card_monitor.update_from_move(move,args)
        return True, ""
    
    def _make_mock_move(self,move,args) -> GameState:
        """ Makes a move, like '_make_move', but returns the game state after the move and restores self and attributes to its original state.
        """
        # Save information about the game state
        curr_state = GameState.from_game(self)
        curr_card_monitor_player_cards = copy.deepcopy(self.card_monitor.player_cards)
        curr_card_monitor_cards_fall_dict = copy.deepcopy(self.card_monitor.cards_fall_dict)
        curr_tc_ptr = self.turnCycle.ptr
        curr_deck_state = copy.deepcopy(self.deck.cards)
        curr_pl_hands = {pl.pid:pl.hand.copy() for pl in self.players}
        # Normally play the move; change games state precisely as it would actually change.
        success, msg = self._make_move(move,args)
        if not success:
            raise AssertionError(f"Mock move failed: {msg}")
        # Save the new game state, for evaluation of the move
        new_state = GameState.from_game(self)
        
        # Restore the game state to its original state
        # Restore the turn cycle
        self.turnCycle.ptr = curr_tc_ptr
        # Restore the deck
        self.deck.cards = curr_deck_state
        # Restore the players ACTUAL hands
        for pid, hand in curr_pl_hands.items():
            self.players[pid].hand = hand
        # Restore the cards on the table; fell cards and cards_to_fall
        self.fell_cards = curr_state.fell_cards
        self.cards_to_fall = curr_state.cards_on_table
        
        # Restore card monitors Fall dictionary, and MONITORED player hands
        self.card_monitor.cards_fall_dict = curr_card_monitor_cards_fall_dict
        self.card_monitor.player_cards = curr_card_monitor_player_cards
    
        
        if self.card_monitor.cards_fall_dict != curr_card_monitor_cards_fall_dict:
            print("Fall dict was: ",curr_card_monitor_cards_fall_dict)
            print("Fall dict is: ",self.card_monitor.cards_fall_dict)
            raise AssertionError(f"Mock move failed: Incorrect fall dict!")
        
        if self.card_monitor.player_cards != curr_card_monitor_player_cards:
            print("Player CARD MONITOR cards were: ",{self.players[pid].name : cards for pid, cards in enumerate(curr_state.player_cards)})
            print("Player CARD MONITOR cards are: ",self.card_monitor.player_cards)
            raise AssertionError(f"Mock move failed: Incorrect card monitor!")
        
        # The actual hands on players
        restored_hands = {pl.pid:pl.hand for pl in self.players}
        if curr_pl_hands != restored_hands:  # Check that the hands are the same
            print("Actual hands were: ",curr_pl_hands)
            print("Actual hands are: ",restored_hands)
            print("Difference: ", list(set(curr_pl_hands.items()) - set(restored_hands.items())))
            raise AssertionError(f"Mock move failed: Incorrect player hands!")
        
        if curr_tc_ptr != self.turnCycle.ptr:
            print("TC was: ",curr_tc_ptr)
            print("TC is: ",self.turnCycle.ptr)
            raise AssertionError(f"Mock move failed: Incorrect turn cycle pointer!")
        
        if curr_deck_state != self.deck.cards:
            print("Deck was: ",curr_deck_state)
            print("Deck is: ",self.deck.cards)
            raise AssertionError(f"Mock move failed: Incorrect order of deck!")
        
        if curr_state.fell_cards != self.fell_cards:
            print("Fell cards were: ",curr_state.fell_cards)
            print("Fell cards are: ",self.fell_cards)
            raise AssertionError(f"Mock move failed: Incorrect fell cards!")
        
        if curr_state.cards_on_table != self.cards_to_fall:
            print("Cards to fall were: ",curr_state.cards_on_table)
            print("Cards to fall are: ",self.cards_to_fall)
            raise AssertionError(f"Mock move failed: Incorrect cards to fall!")
        
        if curr_state.as_vector(normalize=False) != GameState.from_game(self).as_vector(normalize=False):
            print("State was: ",curr_state.as_vector(normalize=False))
            print("State is: ",GameState.from_game(self).as_vector(normalize=False))
            raise AssertionError(f"Mock move failed: Incorrect state vector! {msg}")
        return new_state
        
        
    
    
    def __repr__(self) -> str:
        """ What to print when calling print(self) """
        s = f"Triumph card: {self.triumph_card}\n"
        for pl in self.players:
            s += f"{pl.name}{'*' if pl is self.get_target_player() else ''} : {self.card_monitor.player_cards[pl.name]}\n"
        s += f"Cards to fall : {self.cards_to_fall}\n"
        s += f"Fell cards : {self.fell_cards}\n"
        return s
    
    def _start_player_threads(self) -> None:
        """ Starts all player threads. """
        self.cards_to_fall.clear()
        self.fell_cards.clear()
        # Add self to allowed threads
        self.threads[threading.get_native_id()] = self
        with self.get_lock() as ml:
            for pl in self.players:
                tid = pl._start()
                self.threads[tid] = pl
            self.glog.debug("Started player threads")
            assert len(set([pl.pid for pl in self.players])) == len(self.players), f"A non-unique player id ('pid' attribute) found."
            self.card_monitor.start()
        return
    
    def _join_threads(self) -> None:
        """ Join all threads. """
        for pl in self.players:
            pl.thread.join(self.timeout,)
            if pl.thread.is_alive():
                with self.get_lock() as ml:
                    self.glog.error(f"Player {pl.name} thread timedout. Exiting.")
                    pl.plog.error(f"Thread timedout!")
                    print(f"Game with log {self.log_file} failed.")
                    self.EXIT_FLAG = True
                    return False
                #raise multiprocessing.ProcessError(f"Game with log {self.log_file} failed.")
        self.glog.debug("Threads finished")
        return True
    
    
    def get_initiating_player(self) -> AbstractPlayer:
        """ Return the player, whose turn it is/was to initiate the turn aka. play to an empty table. """
        active = self.get_target_player()
        ptr = int(self.turnCycle.ptr)
        out = self.turnCycle.get_prev_condition(cond = lambda x : x.rank is None and x is not active,incr_ptr=False)
        #self.turnCycle.set_pointer(ptr)    #TODO: This should work fine without this line.
        assert self.turnCycle.ptr == ptr, "Problem with turnCycle"
        return out
    
    def get_players_condition(self, cond : Callable = lambda x : True) -> List[AbstractPlayer]:
        """ Get a list of players that return True when condition is applied.

        Args:
            cond (Callable): The condition to be applied to each AbstractPlayer -instance. Defaults to lambda x : True.

        Returns:
            List of players who satisfy condition.
        """
        return list(filter(cond,self.players))
    
    def add_cards_to_fall(self,add : List[Card]) -> None:
        """Add a list of cards to fall.

        Args:
            add (List): The list of cards to add to the table.
        """
        self.cards_to_fall += add
        return
        
    def get_target_player(self) -> AbstractPlayer:
        """Return the player, who is currently the target; To who cards are played to.

        Returns:
            Player.MoskaPlayerBase: the target player
        """
        return self.turnCycle.get_at_index()
    
    def _set_triumph(self) -> None:
        """Sets the triumph card of the MoskaGame.
        Takes the top-most card, checks the suit, and checks if any player has the 2 of that suit in hand.
        If some player has, then it swaps the cards.
        Places the card at the bottom of the deck.
        """
        assert len(self.players) > 1 and len(self.players) < 8, "Too few or too many players"
        triumph_card = self.deck.pop_cards(1)[0]
        self.triumph = triumph_card.suit
        p_with_2 = self.get_players_condition(cond = lambda x : any((x.suit == self.triumph and x.value==2 for x in x.hand.cards)))
        if p_with_2:
            assert len(p_with_2) == 1, "Multiple people have valtti 2 in hand."
            p_with_2 = p_with_2[0]
            p_with_2.hand.add([triumph_card])
            triumph_card = p_with_2.hand.pop_cards(cond = lambda x : x.suit == self.triumph and x.value == 2)[0]
            self.glog.info(f"Removed {triumph_card} from {p_with_2.name}")
        self.triumph_card = triumph_card
        self.deck.place_to_bottom(self.triumph_card)
        self.glog.info(f"Placed {self.triumph_card} to bottom of deck.")
        return
    
    def start(self) -> bool:
        """The main method of MoskaGame. Sets the triumph card, locks the game to avoid race conditions between players,
        initializes and starts the player threads.
        After that, the players play the game, only one modifying the state of the game at a time.

        Returns:
            True when finished
        """
        self._set_triumph()
        self._create_locks()
        self.glog.info(f"Starting the game with seed {self.random_seed}...")
        self._start_player_threads()
        self.glog.info(f"Started moska game with players {[pl.name for pl in self.players]}")
        # Wait for the threads to finish
        success = self._join_threads()
        if not success:
            return None, None
        self.glog.info("Final ranking: ")
        ranks = [(p.name, p.rank) for p in self.players]
        losers = []
        not_losers = []
        # Combine the players vectors into one list
        for pl in self.players:
            # If the player lost, append 0 to the end of the vector, else append 1
            pl_not_lost = 0 if pl.rank == len(self.players) else 1
            for state in pl.state_vectors:
                if pl_not_lost == 0:
                    losers.append(state + [0])
                else:
                    not_losers.append(state + [1])
                
        state_results = losers + random.sample(not_losers,min(len(losers),len(not_losers)))
        state_results.sort(key = lambda x : random.random())
        #print(f"Losers: {len(losers)}, Not losers: {len(not_losers)}")
        #print(f"Writing {len(state_results)} vectors to file.")

        def get_file_name(min_val = 0, max_val = 1000000000):
            fname = "data_"+str(random.randint(min_val,max_val))+".out"
            tries = 0
            while os.path.exists(fname) and tries < 1000:
                fname = "data_"+str(random.randint(0,max_val))+".out"
                tries += 1
            if tries == 1000:
                print("Could not find a unique file name. Saving to custom file name.")
                fname = "data_new_"+str(random.randint(0,max_val))+".out"
            return fname
        
        #print(f"Writing {len(state_results)} vectors to file.")
        with open("Vectors/"+get_file_name(),"w") as f:
            data = str(state_results).replace("], [","\n")
            data = data.strip("[]")
            f.write(data)
        
        ranks = sorted(ranks,key = lambda x : x[1] if x[1] is not None else float("inf"))
        for p,rank in ranks:
            self.glog.info(f"#{rank} - {p}")
        # Clean up just in case.
        for pl in self.players:
            del pl
        del self.card_monitor, self.turnCycle, self.deck, self.players
        return ranks, state_results