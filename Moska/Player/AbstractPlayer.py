from __future__ import annotations
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Set, Tuple
from ..Deck import Card
if TYPE_CHECKING:   # False at runtime, since we only need MoskaGame for typechecking
    from ..Game import MoskaGame
from ..Hand import MoskaHand
from .. import utils
import threading
import time
import logging
import sys
import traceback
from abc import ABC, abstractmethod


class AbstractPlayer(ABC):
    hand : MoskaHand = None
    pid : int = 0
    moskaGame : MoskaGame = None
    rank : int = None
    thread : threading.Thread = None
    name : str = ""
    ready : bool = False
    delay : float = 10**-6
    requires_graphic : bool = False
    debug : bool = False
    plog = None
    log_level = logging.INFO
    log_file : str = "P"
    thread_id = None
    move_map = {}
    def __init__(self,
                 moskaGame : MoskaGame = None, 
                 pid : int = 0, 
                 name : str = "", 
                 delay=10**-6,
                 requires_graphic : bool = False,
                 debug : bool = False,
                 log_level = logging.INFO,
                 log_file = ""):
        self.moskaGame = moskaGame
        self.pid = pid
        self.log_level = log_level
        self.name = name if name else f"B0-{str(pid)}"
        self.log_file = log_file
        self.delay = delay
        self.requires_graphic = requires_graphic
        self.debug = debug
        self.moves = {
            "EndTurn" : self._end_turn,
            "InitialPlay" : self._play_initial,
            "PlayToOther" : self._play_to_target,
            "PlayToSelf" : self._play_to_self,
            "PlayFallFromHand" : self._play_fall_card_from_hand,
            "PlayFallFromDeck" : self._play_fall_from_deck,
            "Skip" : self._skip_turn,
        }
    
    def _set_plogger(self) -> None:
        """ Sets the logger for this player.
        Can be called explicitly or with self.log_file=....
        NOTE: This must be called AFTER starting the process in which this player is run in.
        Currently this is called in the `_start` method, which is called from Game when the game begins.
        """        
        plog = logging.getLogger(self.name)
        plog.setLevel(self.log_level)
        fh = logging.FileHandler(self.log_file,mode="w",encoding="utf-8")
        formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
        fh.setFormatter(formatter)
        plog.addHandler(fh)
        self.plog = plog
        assert self.plog.hasHandlers(), "Logger has no handles"
        assert not self.plog.disabled, "Logger is disabled"
        self.plog.debug("Logger succesful")
        return
        
    def _set_moskaGame(self) -> None:
        """Sets the moskaGame instance. called from __setattr__.
        """
        self.hand = MoskaHand(self.moskaGame)
        return
    
    def __setattr__(self, name : str, value : Any) -> None:
        """Called when setting a variable in this instance.

        Args:
            name (str): value to set
            value (Any): set value to what
        """
        super.__setattr__(self, name, value)
        if name == "moskaGame" and value is not None:
            self._set_moskaGame()
    
    def _set_pid(self,pid) -> None:
        """ Set the players pid. Currently no use."""
        self.pid = pid
        self.plog.debug(f"Set pid to {pid}")
    
    def _playable_values_to_table(self) -> Set[int]:
        """Return a set of integer values that can be played to the table.
        This equals the set of values, that have been played to the table.

        Returns:
            set: Which values have been played to the table
        """
        return set([c.value for c in self.moskaGame.cards_to_fall + self.moskaGame.fell_cards])
    
    def _playable_values_from_hand(self) -> Set[int]:
        """Return a set of values, that can be played to target.
        This is the intersection of values between the values in the table, and in the players hand.

        Returns:
            set: intersection of played values and values in the hand
        """
        return self._playable_values_to_table().intersection([c.value for c in self.hand])
    
    def _fits_to_table(self) -> int:
        """Return the number of cards playable to the active/target player.
        This equals the number of cards in the targets hand,
        minus the number of (unfallen) cards on the table.

        Returns:
            int: How many cards can be played to the target
        """
        target = self.moskaGame.get_target_player()
        return len(target.hand) - len(self.moskaGame.cards_to_fall)
    
    
    def _play_to_target(self) -> List[AbstractPlayer,List[Card]]:
        """ This method is invoked to play the cards, chosen in 'play_to_target' """
        play_cards = self.play_to_target()
        target = self.moskaGame.get_target_player()
        self.plog.info(f"Playing {play_cards} to {target.name}")
        #self._playToOther(target,play_cards)
        return [target, play_cards]
    
    def _skip_turn(self) -> List:
        return []
        
    def _play_to_self(self) -> List[AbstractPlayer,List[Card]]:
        """ Play cards selected in play_to_self to self
        """
        play_cards = self.play_to_self()
        self.plog.info(f"Playing {play_cards} to self.")
        #self._playToOther(self,play_cards)
        return [self, play_cards]
    
    
    def _play_initial(self) -> List[AbstractPlayer,List[Card]]:
        """ This function is called, when self is the initiating player, and gets to play to an empty table.
        """
        target = self.moskaGame.get_target_player()
        play_cards = self.play_initial()
        self.plog.info(f"Playing {play_cards} to {target.name}")
        #self._initialPlay(target,play_cards)
        return [target, play_cards]
    
    def _can_end_turn(self) -> bool:
        """ Return True if the player CAN end their turn now.
        Which is true, when all the other players are ready and there are cards on the table.
        """
        players_ready = all((pl.ready for pl in self.moskaGame.players if (pl is not self) and (pl.rank is None)))
        cards_in_table = len(self.moskaGame.cards_to_fall) + len(self.moskaGame.fell_cards) > 0
        return players_ready and cards_in_table
    
    def _must_end_turn(self) -> bool:
        """Player must end their turn if:
        - There are cards on the table
        - They have no playable cards
        - All players are ready
        - And the player cant koplata (there is no deck left or there is a kopled card already)
        """
        if self._can_end_turn() and not self._can_fall_cards() and not self._playable_values_from_hand() and (len(self.moskaGame.deck) == 0 or any(c.kopled for c in self.moskaGame.cards_to_fall)):
            return True
        return False
    
    def _can_fall_cards(self) -> bool:
        """ Returns True if the player can fall cards from table with cards in their hand

        Returns:
            bool: _description_
        """
        for pc in self.hand:
            for fc in self.moskaGame.cards_to_fall:
                 if utils.check_can_fall_card(pc,fc,self.moskaGame.triumph):
                     return True
        return False

    def _play_fall_from_deck(self) -> None:
        """ This method is called, when the player decides to koplata.
        """
        #self._playFallFromDeck(fall_method=self.deck_lift_fall_method)
        return [self.deck_lift_fall_method]

    def _play_fall_card_from_hand(self) -> None:
        """ This method is called, when the player has decided to play cards from their hand.
        """
        play_cards = self.play_fall_card_from_hand()
        self.plog.info(f"Falling cards: {play_cards}")
        #self._playFallCardFromHand(play_cards)
        return [play_cards]
    
    def _end_turn(self) -> List[List[Card]]:
        """Called when the player must or wants to and can end their turn, or when finishing the game

        Returns:
            bool: True if cards were picked, false otherwise
        """
        pick_cards = []
        # If the player didn't finish fully, ask which cards to pick to hand
        if self.rank is None:
            pick_cards = self.end_turn()
        self.plog.info(f"Ending turn and picking {pick_cards}")
        #self._endTurn(pick_cards)
        return [pick_cards]
        
    def _set_rank(self) -> int:
        """Set the players rank. Rank is None, as long as the player is still in the game.
        This is called after each turn.
        """
        if self.rank is None:   # if the player hasn't already finished
            # If the player doesn't have a hand and there are no cards left, or there are no players left
            if (not self.hand and len(self.moskaGame.deck) == 0) or len(self.moskaGame.get_players_condition(cond = lambda x : x.rank is None)) <= 1:
                self.rank = len(self.moskaGame.get_players_condition(cond = lambda x : x.rank is not None)) + 1
        self.plog.debug(f"Set rank to {self.rank}")
        return self.rank
    
    @utils.check_new_card
    def _play_move(self) -> Tuple[bool,str]:
        """Calls moskaGame to propose a move.
        This is called on each turn from _continuous play

        Returns:
            Tuple[bool,str]: _description_
        """
        success = False
        playable = self._playable_moves()
        move = self.choose_move(playable)
        args = [self] + self.moves[move]()
        success, msg  = self.moskaGame._make_move(move,args)
        return success, msg
    
    def _playable_moves(self) -> List[str]:
        """Return the playable moves as a dictionary of move-name : play_function

        Returns:
            list[str]: List of playable move identifiers
        """
        playable = list(self.moves.keys())
        # If the player has already played the desired cards, and he is not the target
        # If the player is the target, he might not want to play all cards at one turn, since others can then put same value cards to the table
        self.ready = True
        # If there are cards on the table; the game is already initiated
        initiated = int(len(self.moskaGame.cards_to_fall) + len(self.moskaGame.fell_cards)) != 0
        # Special case: if the player has played all their cards in the previous turn, they must now end the turn and finish
        if self.rank is not None:
            if self is self.moskaGame.get_target_player():
                playable = ["EndTurn"]
            else:
                playable = ["Skip"]
        # If player is the target
        elif self is self.moskaGame.get_target_player():
            # If the player is the target, they cant play these
            playable.remove("PlayToOther")
            playable.remove("InitialPlay")
            # If the player can not end their turn, they cant end the turn, unless they are finished
            if not self._can_end_turn():
                playable.remove("EndTurn")
            # If there are not values to play to self
            if not self._playable_values_from_hand() or len(self.moskaGame.deck) == 0:
                playable.remove("PlayToSelf")
            # If there are no cards to play from hand
            if not self._can_fall_cards():
                playable.remove("PlayFallFromHand")
            # If there is no deck left, or there is already a kopled card on the table, or there are no cards to fall
            if any((c.kopled for c in self.moskaGame.cards_to_fall)) or len(self.moskaGame.deck) <= 0 or not self.moskaGame.cards_to_fall:
                playable.remove("PlayFallFromDeck")
            # If all players are ready and there are no other moves left
            if self._must_end_turn():
                playable.remove("Skip")
                assert len(playable) == 1, f"There should only be 'end turn' option left. Left options: {playable.keys()}"
        else:
            # If the player is not the target player
            playable.remove("PlayFallFromDeck")
            playable.remove("PlayFallFromHand")
            playable.remove("EndTurn")
            playable.remove("PlayToSelf")
            # If the player doesn't have cards to play from hand, or the table is full
            if not self._playable_values_from_hand() or self._fits_to_table() <= 0:
                playable.remove("PlayToOther")
            # If the player is the initiating player and the game is not initiated, they cant skip
            if self is self.moskaGame.get_initiating_player() and not initiated:
                playable.remove("Skip")
            # If the game is initiated, or the player isn't the initiating player, they cant initiate the turn
            if initiated or not self is self.moskaGame.get_initiating_player():
                playable.remove("InitialPlay")
        assert bool(playable), f"There must be something to play"
        self.plog.debug(f"Playable moves: {playable}")
        return playable
    
    def _start(self) -> int:
        """ Initializes the players thread, starts the thread and returns the threads identification get_ident() """
        if self.thread is None or not self.thread.is_alive():
            self._set_plogger()
            self.thread = threading.Thread(target=self._continuous_play,name=self.name)
            self.plog.info("Initialized thread")
            self.thread.start()
            self.thread_id = self.thread.ident
        return self.thread_id
    
    def _continuous_play(self) -> None:
        """ The main method of MoskaPlayer. This method is meant to be run indirectly, by starting the Thread associated with the player.
        This function starts a while loop, that runs as long as the players rank is None and there are atleast 2 players in the game.
        """
        tb_info = {"players" : len(self.moskaGame.players),
                   "Triumph card" : self.moskaGame.triumph_card,
                   }
        self.plog.info(f"Table info: {tb_info}")
        while self.rank is None:
            time.sleep(self.delay)     # To avoid one player having the lock at all times, due to a small delay when releasing the lock. This actually makes the program run faster
            # Acquire the lock for moskaGame
            with self.moskaGame.get_lock(self) as ml:
                msgd = {
                    "target" : self.moskaGame.get_target_player().name,
                    "cards_to_fall" : self.moskaGame.cards_to_fall,
                    "fell_cards" : self.moskaGame.fell_cards,
                    "hand" : self.hand,
                    "Deck" : len(self.moskaGame.deck),
                    }
                # If a human is playing, then we print the values to terminal
                if self.requires_graphic:
                    print(f"{self.name} playing...",flush=True)
                    print(self.moskaGame,flush=True)
                    print(msgd, flush=True)
                # If there is only 1 active player in the game, the player is last
                if len(self.moskaGame.get_players_condition(lambda x : x.rank is None)) <= 1:
                    self._set_rank()
                    break
                self.plog.debug(f"{msgd}")
                try:
                    # Try to play moves, as long as a valid move is played.
                    success, msg = self._play_move()    # Return (True, "") if a valid move, else (False, <error>)
                    while not success:
                        self.plog.warning(msg)
                        self.ready = False
                        print(msg, flush=True)
                        success, msg = self._play_move()
                except Exception as e:
                    self.plog.error(traceback.format_exc())
                    sys.exit(e)
                # Set the players rank
                self._set_rank()
                # Check if self is target and finished
                if self.rank is not None and self is self.moskaGame.get_target_player():
                    self.moskaGame._make_move("EndTurn",[self,[]])
        self.plog.info(f"Finished as {self.rank}")
        return
    
    def _count_score(self,card : Card):
        """Return how many cards can the input card fall;
        How many cards are smaller and same suit
        or if suit is triumph, how many cards are not triumph or are smaller triumph cards.

        Args:
            card (Card): The card for which to count the score

        Returns:
            int: How many cards the card can fall
        """
        if card.suit == self.moskaGame.triumph:
            return 4*13 - (14 - card.value)
        else:
            return 12 - (14 - card.value)
    
    def _assign_scores(self, cards : Iterable[Card]) -> List[Card]:
        """Create new Card instances, with the Card instances from Iterable.
        Return the new cards

        Args:
            cards (Iterable[Card]): The cards which are copied to the new list of cards, along with the score
            
        Returns:
            List[Card]: list of the same cards, with a score -attribute
        """
        new_cards = []
        for card in cards:
            card.score = self._count_score(card)
            new_cards.append(card)
        return new_cards
    
    def _map_to_list(self,card : Card, to : Iterable[Card] = None) -> List[Card]:
        """Return a list of Card -instances selected from 'to' (default self.moskaGame.cards_to_fall),
        that 'card' can fall.

        Args:
            card (Card): The card that is used to fall cards in 'to'
            to (Iterable[Card], optional): Iterable containing Card -instances. Defaults to cards_on_table.

        Returns:
        List[Card]: List of Card -instances
        """
        if not to:
            to = self.moskaGame.cards_to_fall
        out = []
        for c in to:
            if utils.check_can_fall_card(card,c,self.moskaGame.triumph):
                out.append(c)
        return out
    
    def _get_sm_score_in_list(self,cards : List[Card]):
        """Return the first Card with the smallest score in 'cards'.

        Args:
            cards (List[Card]): _description_

        Returns:
            _type_: _description_
        """        
        if not cards:
            return None
        cards = self._assign_scores(cards)
        sm_score = min((c.score for c in cards))
        return list(filter(lambda x : x.score == sm_score,cards))[0]
    
    
    @abstractmethod
    def choose_move(self,playable : List[str]) -> str:
        """ Select a move to play.

        Args:
            Playable (List[str]): A list of the available plays as string identifiers

        Returns:
            str: The move identifier that you want to play.
        """
        pass
    
    @abstractmethod
    def end_turn(self) -> List[Card]:
        """Return which cards you want to pick from the table WHEN you have finished your turn.
        
        Returns:
            list : List of cards to pick from the table
        
        """
        pass
    
    @abstractmethod
    def play_fall_card_from_hand(self) -> Dict[Card,Card]:
        """Return a dictionary of card_in_hand : card_in_table -pairs, denoting which card is used to fall which card on the table.
        This function is called when the player has decided to play from their hand.
        Returns:
            Dict[Card,Card]: Card-in-hand - card-on-table pairs
        """
        pass
    
    @abstractmethod
    def deck_lift_fall_method(self, deck_card : Card) -> Tuple[Card,Card]:
        """A function to determine which card on the table will fall, if a random card from the deck is lifted.
        Function takes a card -instance as argument, and returns a pair (card_from_deck , card_on_table) in the same order,
        determining which card on the table to fall.
        
        This function is called, when the player decides to koplata AND the koplattu card can fall a card on the table.
        If the koplattu card can't fall any card on the table, then the card is just placed on the table, WITHOUT CALLING THIS FUNCTION.
        
        When this function is called, it is guaranteed, that there is a card on the table that can be falled with the card from deck.
        
        NOTE: If this function returns a pair, that doesn't work, then a random card is chosen.

        Args:
            deck_card (Card): The lifted card from the deck

        Returns:
            tuple(Card,Card): The input card from deck, the card on the table.
        """
        pass
    
    @abstractmethod
    def play_to_self(self) -> List[Card]:
        """Which cards from hand to play to table.
        
        Returns:
            List[Card]: list of cards played to self
        """
        pass
    
    @abstractmethod
    def play_initial(self) -> List[Card]:
        """Return a list of cards that will be played to target on an initiating turn. AKA playing to an empty table.
        This function should always return a non empty list.
        Returns:
            List[Card]: _description_
        """
        pass
    
    @abstractmethod
    def play_to_target(self) -> List[Card]:
        """Return a list of cards, that will be played to target.
        This function is called, when there are cards on the table, and you can play cards to a target

        Returns:
            List[Card]: List of Card -instances from hand, that can be played to the target.
        """
        pass