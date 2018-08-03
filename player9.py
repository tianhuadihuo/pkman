#! /usr/bin/env python
# -*- coding:utf-8 -*-

import time
import json
import hashlib
from websocket import create_connection

import sys
sys.path.insert(0, "holdem_calc")
import holdem_calc
import deuces

import numpy as np

from pklearn import Table
from pklearn.templates import simulate, BasicPlayer
from sklearn.ensemble import GradientBoostingRegressor

# pip install websocket-client

ws = ""
pot = 0
my_bet = 0
action_taken = False
my_round_action = dict()
allin_count = dict()
raise_count = dict()
bet_count = dict()
player_count = {
    "Deal" : 0,
    "Flop" : 0,
    "Turn" : 0,
    "River" : 0
}

card_to_score = {
    "2" : 2,
    "3" : 3,
    "4" : 4,
    "5" : 5,
    "6" : 6,
    "7" : 7,
    "8" : 8,
    "9" : 9,
    "T" : 10,
    "J" : 11,
    "Q" : 12,
    "K" : 13,
    "A" : 14
}

def take_action(action="check", amount=0):
    """
    Take an action
    """
    global action_taken
    global my_round_action

    if ("bet" in my_round_action or "raise" in my_round_action) \
        and actin in ["bet", "raise"]:
            action = "call"

    message = {
        "eventName": "__action",
        "data": {}
    }
    message["data"]["action"] = action
    message["data"]["amount"] = int(amount)

    print "==== Take Action ==== : %s %s" % (action, str(amount))
    ws.send(json.dumps(message))
    action_taken = True

def expected_value(win_prob, min_bet):
    """
    Compute expacted value to attend next stage
    """
    global pot
    EV = (((pot + min_bet) * win_prob) - min_bet)
    print "==== Expected value ==== %d" % EV
    return (((pot + min_bet) * win_prob) - min_bet)

def hole_cards_score(hole_cards):
    """
    Calculate a score for hole cards
    Return hish score if we got high cards/pair/possible straight/possible flush
    """
    high_card = 0
    same_suit = 0
    possible_straight = 0
    pair = 0

    base_score = card_to_score[hole_cards[0][0]] + card_to_score[hole_cards[1][0]]
    if base_score > 20:
        high_card =  base_score - 20

    if hole_cards[0][1] == hole_cards[1][1]:
        same_suit = 2

    value_diff = card_to_score[hole_cards[0][0]] - card_to_score[hole_cards[1][0]]
    if value_diff in [-4, 4]:
        possible_straight = 1
    if value_diff in [-3, 3]:
        possible_straight = 2
    if value_diff in [-2, -1, 1, 2]:
        possible_straight = 3
    if value_diff == 0:
        pair = 10

    return (pair + same_suit + high_card + possible_straight ) * base_score

def update_player_count(data):
    """
    Update active player count of current stage
    """
    global player_count
    count = 0
    for player in data["players"]:
        if player["isSurvive"] and not player["folded"]:
            count += 1
    player_count[data["table"]["roundName"]] = count

def player_statistics(players):
    """
    Return the statistics of current players in this round
    """
    global player_count
    global allin_count
    global raise_count
    global bet_count
    playing = 0
    p_stat = {}
    p_stat["v_bet"] = sum(bet_count.values())
    p_stat["v_raise"] = sum(raise_count.values())
    p_stat["v_allin"] = sum(allin_count.values())
    for player in players:
        if not player["playerName"] == my_md5 \
            and not player["folded"]:
            playing += 1
            if player["allIn"]:
                p_stat["v_allin"] += 2
            if player["playerName"] in bet_count:
                p_stat["v_bet"] += bet_count[player["playerName"]]
            if player["playerName"] in raise_count:
                p_stat["v_raise"] += raise_count[player["playerName"]]

    if player_count["Flop"] > 0:
        p_stat["base_line"] = max(player_count["Flop"] - 1, playing)
    else:
        p_stat["base_line"] = max(player_count["Deal"] - 1, playing)

    return p_stat

def virtual_player_count(data):
    """
    Return virtual player count
    Except real player count also considering the bet/raise/allin in this round
    """
    players_stat = player_statistics(data["game"]["players"])
    v_players = int(players_stat["base_line"]
            + players_stat["v_bet"]
            + players_stat["v_raise"]
            + players_stat["v_allin"])
    print "==== Virtual player count ==== %d  = %d + %d + %d + %d" \
            % (v_players,
               players_stat["base_line"],
               players_stat["v_bet"],
               players_stat["v_raise"],
               players_stat["v_allin"])
    return v_players

def calc_win_prob_by_sampling(hole_cards, board_cards, data):
    """
    Calculate the probability to win current players by sampling unknown cards
    Compute the probability to win one player first
    And then take the power of virtual player count
    """
    evaluator = deuces.Evaluator()
    o_hole_cards = []
    o_board_cards = []
    for card in hole_cards:
        o_hole_card = deuces.Card.new(card)
        o_hole_cards.append(o_hole_card)
    for card in board_cards:
        o_board_card = deuces.Card.new(card)
        o_board_cards.append(o_board_card)

    n = 1000
    win = 0
    succeeded_sample = 0
    for i in range(n):
        deck = deuces.Deck()
        board_cards_to_draw = 5 - len(o_board_cards)

        o_board_sample = o_board_cards + deck.draw(board_cards_to_draw)
        o_hole_sample = deck.draw(2)

        try:
            my_rank = evaluator.evaluate(o_board_sample, o_hole_cards)
            rival_rank = evaluator.evaluate(o_board_sample, o_hole_sample)
        except:
            continue
        if my_rank <= rival_rank:
            win += 1
        succeeded_sample += 1
    print "==== sampling result ==== win : %d, total : %d" % (win, succeeded_sample)
    win_one_prob = win/float(succeeded_sample)

    win_all_prob = win_one_prob ** virtual_player_count(data)
    print "==== Win probability ==== " + str(win_all_prob)
    return win_all_prob

def calc_win_prob(hole_cards, board_cards, data):
    """
    Calculate the probability to win current players.
    Compute the probability to win one player first
    And then take the power of virtual player count
    """
    cards_to_evaluate = hole_cards + ["?", "?"]
    exact_calc = True
    verbose = True
    # claculate probability to win a player
    win_one_prob = holdem_calc.calculate(board_cards, exact_calc, 1, None, cards_to_evaluate, verbose)

    win_all_prob = (win_one_prob[0] + win_one_prob[1]) ** virtual_player_count(data)
    print "==== Win probability ==== " + str(win_all_prob)
    return win_all_prob

def evaluate_river(hole_cards, board_cards, data):
    """
    Decide action in river stage
    """
    win_all_prob = calc_win_prob(hole_cards, board_cards, data)
    ev = expected_value(win_all_prob, data["self"]["minBet"])

    if win_all_prob >= 0.9:
        take_action("allin")
    elif win_all_prob >= 0.6:
        amount = min(ev, 0.1 * data["self"]["chips"] + data["self"]["minBet"])
        take_action("bet", amount)
    elif win_all_prob >= 0.4:
        take_action("call")
    elif ev >= 0 and win_all_prob >= 0.2:
        take_action("check")
    else:
        take_action("fold")

def evaluate_turn(hole_cards, board_cards, data):
    """
    Decide action in turn stage
    """
    win_all_prob = calc_win_prob(hole_cards, board_cards, data)
    ev = expected_value(win_all_prob, data["self"]["minBet"])

    if win_all_prob >= 0.8:
        amount = 0.2 * data["self"]["chips"] + data["self"]["minBet"]
        take_action("bet", amount)
    elif win_all_prob >= 0.5:
        amount = min(ev, 0.1 * data["self"]["chips"] + data["self"]["minBet"])
        take_action("bet", amount)
    elif win_all_prob >= 0.4:
        amount = min(ev, 0.05 * data["self"]["chips"] + data["self"]["minBet"])
        take_action("bet", amount)
    elif ev >= 0 and win_all_prob >= 0.15:
        take_action("check")
    else:
        take_action("fold")

def evaluate_flop(hole_cards, board_cards, data):
    """
    Decide action in flop stage
    """
    win_all_prob = calc_win_prob_by_sampling(hole_cards, board_cards, data)
    ev = expected_value(win_all_prob, data["self"]["minBet"])

    if win_all_prob >= 0.8:
        amount = min(ev, 0.1 * data["self"]["chips"] + data["self"]["minBet"])
        take_action("bet", amount)
    elif win_all_prob >= 0.5:
        take_action("raise")
    elif win_all_prob >= 0.3:
        amount = min(ev, 0.05 * data["self"]["chips"] + data["self"]["minBet"])
        take_action("bet", amount)
    elif ev >= 0 and win_all_prob >= 0.15:
        take_action("check")
    else:
        take_action("fold")

def evaluate_deal(hole_cards, data):
    """
    Decide action in deal stage
    """
    v_players = virtual_player_count(data)
    score = hole_cards_score(hole_cards) * (9/float(v_players))

    basic_win_porb = 1/float(v_players)
    ev = expected_value(basic_win_porb, data["self"]["minBet"])

    if score > min(hole_cards_score(["As", "Js"]), hole_cards_score(["Qs", "Qh"])):
        print "==== Judgement is bet ==== score : " + str(score)
        amount = 2 * (data["self"]["minBet"] + 10)
        take_action("bet", amount)
    elif score > min(hole_cards_score(["As", "9s"]), hole_cards_score(["7s", "7h"])):
        print "==== Judgement is bet ==== score : " + str(score)
        amount = 1.5 * (data["self"]["minBet"] + 10)
        take_action("bet", amount)
    elif ev >= 0 or data["self"]["minBet"] <= 20:
        print "==== Judgement is call ==== score : %d ,EV : %d" % (score, ev)
        take_action("call")
    else:
        print "==== Judgement is fold ==== score : " + str(score)
        take_action("fold")

def convert_card_format(card):
    """
    Convert card format so that we could use
    library to evaluate cards
    """
    if len(card) != 2:
        print "Wrong card format"
        return
    return card[0] + card[1].lower()


def getAllActions(toCall, roundBet, stack):
    
    """ This method accepts the dictionary gameState and returns the set of all possible actions. """

    
    rChoices=[0.25, 0.5, 0.75, 1]
    
    #toCall: mount necessary to call
    #minRaise: new total bet amount necessary to raise
    minRaise = toCall*2    
    
    #maxBet: maximum bet player could have in pot, including chips already in pot
    maxBet = roundBet + stack

    actions = []    #set of all possible actions

    if toCall > stack:   #player cannot match entire bet
        actions.append(('call',))
        actions.append(('fold',))
        return actions
        
    if maxBet < minRaise:    #player has enough chips to call but not to raise
        if toCall == 0: actions.append(('check',))
        else: 
            actions.append(('call',))
            actions.append(('fold',))
        return actions

    #add eligible raise choices to actions
    #raise actions include a raise to amount, not a raise by amount
    for r in rChoices:
        amt = int(stack * r) 
        if amt >= minRaise and amt <= maxBet: actions.append(('raise', amt))

    #player has enough chips to raise
    if toCall == 0: actions.append(('check',))
    else:
        actions.append(('call',))
        actions.append(('fold',))
    
    return actions

def genActionFeatures(action, toCall, pot):

    """ This method generates a set of features from a player action. """

    #create binary encoding for action type
    actionFeatures = 7 * [0]

    if action[0] == 'check': actionFeatures[0] = 1
    elif action[0] == 'fold': actionFeatures[1] = 1
    elif action[0] == 'call': actionFeatures[2] = 1
    elif action[0] == 'raise' or action[0] == 'bet':
        actionFeatures[3] = 1
        actionFeatures[4] = action[1]    #raise to amount
        actionFeatures[5] = action[1] - toCall    #raise by amount
        actionFeatures[6] = actionFeatures[5] / pot    #proportion of raise by to pot size
    else: raise Exception('Invalid action.')

    return actionFeatures
    
def evaluate(data, train_player):
    """
    Make decision of each stage
    """
    print "evaluate"
    nEnum = {'2':2, '3':3, '4':4, '5':5,'6':6, '7':7, '8':8, '9':9, 'T':10, 'J':11, 'Q':12, 'K':13, 'A':14}
    
    hole_cards  = [convert_card_format(c) for c in data["self"]["cards"]]
    board_cards = [convert_card_format(c) for c in data["game"]["board"]]
    chips = data["self"]["chips"]
    roundBet = data["self"]["roundBet"]
    toCall = data["self"]["minBet"]
    #toCall = 100
    print "test"
    print "==== my cards ==== " + str(hole_cards)
    print "==== board ==== " + str(board_cards)
    print "==== Current pot ==== %d" % (pot)
    print "==== my stack ======= %d" % (chips)
    print "==== roundBet ======= %d" % (roundBet)
    
    ############################################
    ###       prepare gameFeatures         ####
    cards=sorted(hole_cards)+sorted(board_cards)
    print cards
    card_numbers=[]
    card_suits=[]
    for i in cards:
        card_numbers.append(nEnum[i[0]])
        card_suits.append(i[1])
    print card_numbers
    print card_suits
    
    gameFeatures = 43 * [0]
    for i in range(len(cards)):
        gameFeatures[6 * i] = 1    #ith card exists
        gameFeatures[6 * i + 1] = card_numbers[i]
        suit = card_suits[i]
        
        #create binary encoding for suit
        gameFeatures[6 * i + 2] = suit == 'c' 
        gameFeatures[6 * i + 3] = suit == 'd'
        gameFeatures[6 * i + 4] = suit == 's'
        gameFeatures[6 * i + 5] = suit == 'h'

    #player stack size
    gameFeatures[42] = chips
    print gameFeatures
    ##############################################
    
    
    allActions=getAllActions(toCall, roundBet, chips)
    print allActions
    
    allFeatures = []
    for a in allActions: allFeatures.append(gameFeatures + genActionFeatures(a, toCall, pot))
    pReturn = train_player._reg.predict(allFeatures)
    action = allActions[np.argmax(pReturn)]
    
    print action
    
    if action[0] == "raise":
        take_action("raise", action[1])
    else:
        take_action(action[0])
    '''
    if data["game"]["roundName"] == "Deal":
        evaluate_deal(hole_cards, data)
    elif data["game"]["roundName"] == "Flop":
        evaluate_flop(hole_cards, board_cards, data)
    elif data["game"]["roundName"] == "Turn":
        evaluate_turn(hole_cards, board_cards, data)
    elif data["game"]["roundName"] == "River":
        evaluate_river(hole_cards, board_cards, data)
    '''

def react(event, data, trained_player):
    """
    React to events
    """
    global bet_count
    global raise_count
    global allin_count
    global my_round_action
    global player_count
    global my_bet
    global pot
    global action_taken
    action_taken = False

    if event == "__new_peer":
        pass
    elif event == "__new_peer_2":
        pass
    elif event == "_join":
        pass
    elif event == "__show_action":
        if data["action"]["playerName"] == my_md5:
            if "amount" in data["action"]:
                my_bet += data["action"]["amount"]

        pot = data["table"]["totalBet"]
        if data["action"]["action"] == "allin":
            if data["action"]["playerName"] in allin_count:
                allin_count[data["action"]["playerName"]] += 1
            else:
                allin_count[data["action"]["playerName"]] = 1
        if data["action"]["action"] == "raise":
            if data["action"]["playerName"] in raise_count:
                raise_count[data["action"]["playerName"]] += 1
            else:
                raise_count[data["action"]["playerName"]] = 1
        if data["action"]["action"] == "bet":
            if data["action"]["playerName"] in bet_count:
                bet_count[data["action"]["playerName"]] += 1
            else:
                bet_count[data["action"]["playerName"]] = 1
    elif event == "__deal":
        my_round_action = dict()
        update_player_count(data)
        print "==== Player count in %s ==== %d" % (data["table"]["roundName"], player_count[data["table"]["roundName"]])
    elif event == "__start_reload":
        ws.send(json.dumps({"eventName" : "__reload"}))
    elif event == "__round_end":
        for player in data["players"]:
            if player["playerName"] == my_md5:
                if player["winMoney"] > 0:
                    print "==== Round end : Win money!! ==== %d" % ( player["winMoney"])
                else:
                    print "==== Round end : Cheer up! ==== Loss bet : %d" % (my_bet)

    elif event == "__new_round":
        my_bet = 0
        pot = 0
        allin_count = dict()
        raise_count = dict()
        bet_count = dict()
        player_count = {
            "Deal" : 0,
            "Flop" : 0,
            "Turn" : 0,
            "River" : 0
        }
    elif event == "__bet":
        #time.sleep(2)
        evaluate(data, trained_player)
        if not action_taken :
            take_action("bet", 10)
    elif event == "__action":
        #time.sleep(2)
        evaluate(data, trained_player)
        if not action_taken :
            take_action("check")
    elif event == "__game_over":
        max_chips = 0
        my_chips = 0
        for winner in data["winners"]:
            if winner["chips"] > max_chips:
                max_chips = winner["chips"]
            if winner["playerName"] == my_md5:
                my_chips = winner["chips"]
        if my_chips == max_chips:
            print "==== Game over : YOU ARE THE WINNER!! ==== Final chips %d" % max_chips
        else:
            print "==== Game over : So close... ==== %d vs %d" % (my_chips, max_chips)
    else:
        print "==== unknown event ==== : " + event


def doListen(player):
    try:
        global ws
        ws = create_connection("ws://pokerai.trendmicro.com.cn")
        #ws = create_connection("ws://10.64.8.72")
        ws.send(json.dumps({
            "eventName": "__join",
            "data": {
                "playerName": my_id
            }
        }))
        while 1:
            result = ws.recv()
            msg = json.loads(result)
            event_name = msg["eventName"]
            data = msg["data"]
            print event_name
            #print data
            react(event_name, data, player)
    except Exception, e:
        print e.message
        doListen(player)


if __name__ == '__main__':

    my_id = "pk-man"
#    my_id = "730908575451990f4f3dc625baef4697"
    my_md5 = hashlib.md5(my_id).hexdigest()
#    my_md5 = "730908575451990f4f3dc625baef4697"
    print my_md5
    
    
    try: import matplotlib.pyplot as plt
    except: print 'Must install matplotlib to run this demo.\n'

    t = Table(smallBlind=1, bigBlind=2, maxBuyIn=200)

    players = []
    for i in range(6):
        
        #create BasicPlayer that uses GradientBoostingRegressor as machine learning model
        #with wealth of 1 million and 10 discrete choices for raising,
        #with each raise choice .7 times the next largest raise choice
        #Player forgets training samples older than 100,000
        r = GradientBoostingRegressor()
        name = 'Player ' + str(i+1)
        p = BasicPlayer(name=name, reg=r, bankroll=10000, nRaises=4, rFactor=.7, memory=10**5)
        p.stopTraining()
        players.append(p)

    for p in players: t.addPlayer(p)

    #train Player 1 for 1000 hands, training once
    players[0].startTraining()
    simulate(t, nHands=2000, nTrain=100, nBuyIn=10)   
    players[0].stopTraining()

    #for p in players: p.setBankroll(10**6)

    #simulate 20,000 hands and save bankroll history
    #bankrolls = simulate(t, nHands=20, nTrain=0, nBuyIn=10)

    #plot bankroll history of each player
    '''
    for i in range(6):
        bankroll = bankrolls[i]
        plt.plot(range(len(bankroll)), bankroll, label=players[i].getName())
    plt.title('Player bankroll vs Hands played')        
    plt.xlabel('Hands played')
    plt.ylabel('Player bankroll/wealth')
    plt.legend(loc='upper left')
    plt.show()
    '''
    
    
    doListen(players[0])
