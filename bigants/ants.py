#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import multiprocessing as mp
from multiprocessing import Process, Queue
import time
import pandas as pd
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt
from sklearn import preprocessing
flatten = lambda l: [item for sublist in l for item in sublist]
import seaborn as sns; sns.set(color_codes=True)
from sklearn.cluster import KMeans
import gc



class BiGAnts(object):
    def __init__(self, GE, G, L_g_min, L_g_max):
        self.GE = GE
        self.G = G
        self.L_g_min = L_g_min
        self.L_g_max = L_g_max
    
        
    def run_search(self, n_proc = 1, a = 1, b = 1, K = 20, evaporation = 0.5, th = 0.5, eps = 0.02, 
            times = 6, clusters = 2, cost_limit = 5, max_iter = 200, opt = None,show_pher = False, 
            show_plot = False, save = None, show_nets = False):
        """
        Parallel implementation of bi-graph Ant Colony Optimisation for Biclustering 
        
        Attributes:
        -----------
        non-default:
            
        GE - pandas data frame with gene expression data. Genes are rows, patients - columns
        G - networkx graph with a network
        L_g_min - minimal number of genes in one subnetwork
        L_g_max - minimal number of genes in one subnetwork
        
        default:
        K - number of ants (less ants - less space exploration. Usually set between 20 and 50, default - 20)        
        n_proc = number of processes that should be used (default 1)
        a - pheromone significance (default 1 - does not need to be changed)
        b - heuristic information significance (default 1 - does not need to be changed)
        evaporation - the rate at which pheromone evaporates (default 0.5)
        th - similarity threshold (default 0.5 - does not need to be changed)
        eps - conservative convergence criteria: score_max - score_min < eps (default- 0.02)
        times - allows faster convergence criteria: stop if the maximum so far was reached more than x times (default 6)
        clusters - # of clusters, right now does not work for more than 2
        cost_limit - defines the radius of the search for ants (default 5)
        max_iter - maximum number of itaractions allowed (default 200)
        opt - given if the best score is known apriori (in case of simulated data for instance)
        show_pher - set true if plotting of pheromone heatmap at every iteration is desirable (strickly NOT recommended for # of genes > 2000)
        show_plot - set true if convergence plots should be shown
        save - set an output file name  if the convergence plot should be saved in the end
        show_nets - set true if the selected network should be shown at each iteration
        
        """
        assert self.GE.shape[0] > self.GE.shape[1], "Wrong dimensions of the expression matrix, please pass the transposed version"
        assert n_proc>0, "Set a correct number for n_proc, right now the value is {0}".format(n_proc)
        assert n_proc <= mp.cpu_count()-1, 'n_proc should not exceed {0}. The value of n_proc was: {1}'.format(mp.cpu_count(), n_proc)
        assert n_proc <= K, 'Number of ants (K) can not be lower as number of processes, please set higher K ot lower n_proc'
        #adjacency matrix 
        A = nx.adj_matrix(self.G).todense()
        #hurisic information 
        H = self.HI_big(self.GE, A)
        H = H.astype(np.short)
        
        n,m = self.GE.shape
        # TODO: rewrite functions such that they all could use numpy matrices
        ge = self.GE.values
        # determination of search radious for each patient
        N = self.neigborhood(H, n, th)
        # inner patients IDs
        patients = np.arange(n, n+m)  
        #cost of transitions for ants
        cost = H/10
        cost = np.max(cost)-cost
        #stores all scores
        scores = []
        avs = []
        count_big = 0
        max_total_score = 0
        max_round_score = -100
        av_score = 0
        # initial pheramone level set to a maximal possible level (5 standart deviations)
        t0 = np.ones((n+m, n+m))*5
        t0 = t0.astype(np.short)
        t_min = 0
        #initial probabilities 
        st = time.time()
        probs= self.prob_upd(H, t0, a, b, n, th, N)
        end = time.time()
        # flag tracks when the score stops improoving and terminates the optimization as convergence is reached
        score_change = []
        print ("Run time statistics:")
        print ("###############################################################")
        print("the joint graph has "+ str(n+m) + " nodes")
        print("probability update takes "+str(round(end-st,3)))
        W = 0 #warnongs
        #counts how many times top score was achieved
        count_small = 0            
        #termination if the improvments are getting too small or if there are any computentional warnings
        while np.abs(max_round_score-av_score)>eps and count_small<times and count_big < max_iter:
            #MULTIPROCESSING SCHEMA
            if n_proc > 1:
                av_score = 0
                W = 0
                max_round_score = 0
                result = Queue()
                jobs = []
                ants_per_batch = round(K/n_proc)
                for pr in range(n_proc):
                    #random seed to avoid identical random walks
                    ss = np.random.choice(np.arange(pr*ants_per_batch, pr*ants_per_batch+ants_per_batch), ants_per_batch,replace = False)
                    p = Process(target = self.ant_job_paral, args = (self.GE, N, H, th, clusters, probs, a, b, cost, m, n, patients, count_big, cost_limit, self.L_g_min, self.L_g_max, self.G, ge, ants_per_batch, pr, ss, result,))
                    jobs.append(p)
                    p.start()
                # black magic to synchronize the whole thing 
                while 1:
                    running = any(p.is_alive() for p in jobs)
                    while not result.empty():
                        res = result.get()
                        s1,s2 = res[0]
                        s = s1+s2
                        av_score = av_score+res[-1]
                        #if maximum round score is begger than the current value for this round
                        if s>max_round_score:
                            #save the results
                            max_round_score = s
                            n1 = s1
                            n2 = s2
                            solution,solution_big,_ = res[1:]
                    if not running:
                        break
        
                      
                av_score = av_score/ n_proc       
    
                #after all ants have finished:
                scores.append(max_round_score)
                avs.append(av_score)
                gc.collect()
    
    
            #SINGLE PROCESS SCEMA (RECOMMENDED FOR PC)    
            else:
                st = time.time()
                av_score = 0
                W = 0
                max_round_score = 0
                scores_per_round = []
                st = time.time()
                for i in range(K):
                    #for each ant
                    tot_score, gene_groups, patients_groups, new_scores, wars, no_int = self.ant_job(self.GE, N, H, th, clusters, probs, a, b, cost, m, n, patients, count_big, cost_limit, self.L_g_min, self.L_g_max, self.G, ge)
                    end = time.time()
                    W = W+wars
                    scores_per_round.append(tot_score)
                    av_score = av_score + tot_score
                    if tot_score > max_round_score:
                        max_round_score = tot_score
                        solution = (gene_groups,patients_groups)
                        solution_big = (no_int,patients_groups)
                        n1,n2 = (new_scores[0][0]*new_scores[0][1],new_scores[1][0]*new_scores[1][1])
    
                av_score = av_score/K
                avs.append(av_score)
                #after all ants have finished:
                scores.append(max_round_score)
                if max_round_score == max_total_score:
                    count_small = count_small +1
                end = time.time()
                print("total run-time is {0}".format(end-st))
    
                
            #saving rhe best overall solution
            if np.round(max_round_score,3) == np.round(max_total_score, 3):
                count_small = count_small +1
    
            if max_round_score>max_total_score:
                max_total_score = max_round_score
                best_solution = solution
                solution_big_best = solution_big
                count_small = 0
    
            score_change.append(round(max_round_score,3))
            print("Iteration # "+ str(count_big+1))
            if count_big == 0:
                print("One ant work takes {0} with {1} processes".format(round(time.time()-st, 2), n_proc))
            print("best round score: " + str(round(max_round_score, 3)))
            print("average score: " + str(round(av_score, 3)))
            print("Count small = {}".format(count_small))
            #Pheramone update
            t0 = self.pher_upd(t0,t_min,evaporation,[n1,n2],solution_big_best)
            #Probability update    
            probs= self.prob_upd(H, t0, a, b, n, th, N)
            assert probs[0][0,:].sum() != 0, "bad probability update"
            if count_big == 0:
                print("One full iteration takes {0} with {1} processes".format(round(time.time()-st,2), n_proc))
            count_big = count_big +1
            #visualization options:
    
            
            if show_pher:
                fig = plt.figure(figsize=(18,12))
                ax = fig.add_subplot(111)
                t_max = np.max(t0)   
                cax = ax.matshow(t0, interpolation='nearest', cmap=plt.cm.RdPu, vmin = t_min, vmax = t_max)
                plt.colorbar(cax)
                plt.title("Pheramones")
                plt.show(block=False)
                plt.close(fig)
    
            
            if show_nets:
                self.features(solution, self.GE,self.G)    
            if show_plot:
                fig = plt.figure(figsize=(10,8))
                plt.plot(np.arange(count_big),scores, 'g-')
                plt.plot(np.arange(count_big),avs, '--')
                if opt!=None:
                    plt.axhline(y=opt,label = "optimal solution score", c = "r")
                plt.show(block=False)
                plt.close(fig)
    
        if save != None:
            fig = plt.figure(figsize=(10,8))
            plt.plot(np.arange(count_big),scores, 'g-')
            plt.plot(np.arange(count_big),avs, '--')
            plt.savefig(save+".png")
            plt.close(fig)
            
        #after the solutution is found we make sure to cluster patients the last time with that exact solution:
        data_new = ge[solution[0][0]+solution[0][1],:]
        kmeans = KMeans(n_clusters=2, random_state=0).fit(data_new.T)
        labels = kmeans.labels_
        patients_groups =[]
        for clust in range(clusters):
            wh = np.where(labels == clust)[0]
            group_p = [patients[i] for i in wh]
            patients_groups.append(group_p)
        if np.mean(ge[best_solution[0][0],:][:,(np.asarray(patients_groups[0])-n)])<np.mean(ge[best_solution[0][1],:][:,(np.asarray(patients_groups[0])-n)]):
            patients_groups = patients_groups[::-1]
        best_solution = [best_solution[0],patients_groups]
        
        print("best total score: "+str(max_total_score))
        #print_clusters(GE,best_solution)
        #features(best_solution, GE,G)
        return(best_solution,[count_big, scores, avs])
    

    def ant_job_paral(self, GE, N, H, th, clusters, probs, a, b, cost, m, n, patients, count_big, cost_limit, L_g_min, L_g_max, G, ge, ants_per_batch, pr, ss, result):
        # organising parallel distribution of work between ants batches
        max_round_score = -100
        W = 0
        av_score = 0
        for i in range(ants_per_batch):
            seed = ss[i]
            tot_score, gene_groups, patients_groups, new_scores, wars, no_int = self.ant_job(GE, N, H, th, clusters, probs, a, b, cost, m, n, patients, count_big, cost_limit, L_g_min, L_g_max, G, ge, seed)
            W = W+wars
            av_score = av_score+ tot_score
            if tot_score > max_round_score:
                max_round_score = tot_score
                solution = (gene_groups,patients_groups)
                solution_big = (no_int,patients_groups)
                new_scores_best = new_scores
                s1 = new_scores_best[0][0]*new_scores_best[0][1]
                s2 = new_scores_best[1][0]*new_scores_best[1][1]
        result.put([(s1,s2), solution, solution_big, av_score/ants_per_batch])

    def neigborhood(self, H, n, th):
        #defines search area for each ant
    
        N_per_patient = []
        dim = len(H)
        for i in range(n,dim):
            if th<0:
                N = np.where(H[i,:]>0.001)[0]
            else:
                rad = np.mean(H[i,:]) + th*np.std(H[i,:])
    
                N = np.where(H[i,:]>rad)[0]
            #N = np.where(H[i,:]>0)[0]
            N_per_patient.append(N)
        return N_per_patient


    def prob_upd(self, H, t, a, b, n, th, N_per_patient):
        #updates probability
        P_per_patient = []
        dim = len(H)
        temp_t = np.power(t,a)
        temp_H = np.power(H,b)
        temp = temp_t*temp_H 
    
        for i in range(n,dim):
            N_temp = N_per_patient[i-n]
            P = temp[:,N_temp]
            s = np.sum(P,axis = 1)
            s[s <1.e-4] = 1
            sum_p = 1/s
            sum_p = sum_p[:,None]
            P_new = P*sum_p[:np.newaxis]
            P_per_patient.append(P_new)
    
        return(P_per_patient)
        
    
    def walk(self, start, Nn, P_small, cost, k, n, seed = None):
        #Initialize a random walk
        path = []
        path.append(start)
        go = True
        while go == True:
            P_new = P_small[start,:]
            #if there is any node inside the radious - keep mooving
            if np.sum(P_new)> 0.5:
                #transition:
                if seed != None:
                    np.random.seed(seed)
                tr = np.random.choice(Nn,1,False,p = P_new)[0]
                c = cost[start,tr]
                #if there is any cost left we keep going
                if k-c >0:
                    path.append(tr)
                    start = tr
                    k = k - c
                #if not we are done and we save only genes from the path
                else:
                    go = False
            #no node to go - we are done and we save only genes from the path
            else:
                go = False
        path = np.asarray(path)
        path = path[path<n]
        #we are saving only genes
        return(path)

        


  

    def ant_job(self, GE, N, H, th, clusters, probs, a, b, cost, m, n, patients, count_big, cost_limit, L_g_min, L_g_max, G, ge, seed = None):
    
        paths = []
        wars = 0
        #set an ant on every patient
        for w in range(m):
            #print(w)
            k = cost_limit
            start = patients[w]
            Nn = N[w] #neigbohood
            P_small = probs[w]
            path = self.walk(start,Nn,P_small,cost,k,n)
            paths.append(path)
    #    print("Random walks: {0}\n".format(end-st))
        data_new = ge[list(set(flatten(paths))),:]
        kmeans = KMeans(n_clusters=2).fit(data_new.T)
        labels = kmeans.labels_
    #    print("Patients clustering: {0}\n".format(end-st))
    
        gene_groups_set =[]
        patients_groups =[]
        for clust in range(clusters):
            wh = np.where(labels == clust)[0]
            group_g = [paths[i] for i in wh]
            group_g = flatten(group_g)
            gene_groups_set.append(set(group_g))
            #save only most common genes for a group
            group_p = [patients[i] for i in wh]
            patients_groups.append(group_p)
            
        #delete intersecting genes between groups
        
        I = set.intersection(*gene_groups_set)
        no_int =[list(gene_groups_set[i].difference(I)) for i in range(clusters)]
        gene_groups = no_int
    #    print("Genes clustering: {0}\n".format(end-st))
    
        # make sure that gene clusters correspond to patients clusters:
        if np.mean(ge[gene_groups[0],:][:,(np.asarray(patients_groups[0])-n)])<np.mean(ge[gene_groups[1],:][:,(np.asarray(patients_groups[0])-n)]):
            patients_groups = patients_groups[::-1]
    #    print("Switch: {0}\n".format(end-st))
    
    
        gene_groups,sizes= self.clean_net(gene_groups,patients_groups, clusters,L_g_min,G,GE)
    #    print("Clean net: {0}\n".format(end-st))
    
        new_scores = self.score(G,patients_groups,gene_groups,n,m,ge,sizes,L_g_min,L_g_max)
    #    print("Score: {0}\n".format(end-st))
    
        
        tot_score = new_scores[0][0]*new_scores[0][1]+new_scores[1][0]*new_scores[1][1]   
        return(tot_score,gene_groups,patients_groups,new_scores,wars,no_int)
        
    def pher_upd(self, t, t_min, p, scores, solution):
        t = t*(1-p)
        t_new = np.copy(t)
        assert t_new.sum() > 0, "bad pheramone input"
        for i in range(len(solution[0])):
            group_g = solution[0][i]
            group_p = solution[1][i]
            sc = scores[i]
            #ge_score = new_scores[i][0]*10
            #ppi_score = new_scores[i][1]*10
            for g1 in group_g:
                for p1 in group_p:
                    t_new[g1,p1] = t[g1,p1]+ sc
                    t_new[p1,g1] = t[p1,g1]+ sc
                for g2 in group_g:
                    t_new[g1,g2] = t[g1,g2]+ sc
    
        assert t_new.sum() >=0, "negative pheramone update"
        t_new[t_new < t_min] = t_min
        assert t_new.sum() != 0, "bad pheramone update"
    
        
        return(t_new)
    
        
        
        
        
    def score(self, G, patients_groups, gene_groups, n, m, ge, sizes, L_g_min, L_g_max):
        clusters = len(patients_groups)
        conf_matrix = np.zeros((clusters,clusters))
        conect_ppi = []
        for i in range(clusters): #over genes
            group_g = np.asarray(gene_groups[i])
            s = sizes[i]
            if len(group_g)>0:
                for j in range(clusters): #over patients
                    group_p = np.asarray(patients_groups[j])
                    if len(group_p)>0:
                    # gene epression inside the group
                        conf_matrix[i,j] = np.mean(ge[group_g,:][:,(group_p-n)])
                #ppi score    
                con_ppi = 1
                if s<L_g_min:
                    con_ppi = s/L_g_min
                elif s>L_g_max:
                    con_ppi = L_g_max/s
                conect_ppi.append(con_ppi)
            else:
                conect_ppi.append(0)           
        ans = []
        for i in range(clusters):
            all_ge = np.sum(conf_matrix[i,:])
            in_group = conf_matrix[i,i]
            out_group = all_ge - in_group
            ge_con = in_group-out_group
            #scaled = scaleBetween(num,0,0.5,0,1)
            ans.append((ge_con ,conect_ppi[i]))
            
        return(ans)
    



    def HI_big(self, data_aco, A_new):
        scaler = preprocessing.MinMaxScaler(feature_range=(0, 1))#
        H_g_to_g = (data_aco.T.corr())
        H_p_to_p = data_aco.corr()
        H_g_to_g = scaler.fit_transform(H_g_to_g)
        H_p_to_p = scaler.fit_transform(H_p_to_p)
        H_g_to_p = scaler.fit_transform(data_aco)
        H_full_up = np.concatenate([H_g_to_g,H_g_to_p], axis = 1)
        H_full_down = np.concatenate([H_g_to_p.T,H_p_to_p], axis = 1)
        H_full =  np.concatenate([H_full_up,H_full_down], axis = 0)*10
    #    H_full[H_full < 1] = 1
    #    np.fill_diagonal(H_full, 1)
        np.fill_diagonal(H_full, 0)
        n,_= A_new.shape
        H_small = H_full [:n,:n]
        H_small =np.multiply(H_small,A_new)
        H_full [:n,:n] = H_small
        return(H_full)
    

#    def HI_big(data_aco, A_new):
#        scaler = preprocessing.MinMaxScaler(feature_range=(0, 1))#
#        H_g_to_g = (data_aco.T.corr())
#        H_p_to_p = data_aco.corr()
#        H_g_to_g = scaler.fit_transform(H_g_to_g)
#        H_p_to_p = scaler.fit_transform(H_p_to_p)
#        H_g_to_p = scaler.fit_transform(data_aco)
#        H_full_up = np.concatenate([H_g_to_g,H_g_to_p], axis = 1)
#        H_full_down = np.concatenate([H_g_to_p.T,H_p_to_p], axis = 1)
#        H_full =  np.concatenate([H_full_up,H_full_down], axis = 0)*10
#    #    H_full[H_full < 1] = 1
#    #    np.fill_diagonal(H_full, 1)
#        np.fill_diagonal(H_full, 0)
#        n,_= A_new.shape
#        H_small = H_full [:n,:n]
#        H_small =np.multiply(H_small,A_new)
#        H_full [:n,:n] = H_small
#        return(H_full)


    def print_clusters(self, GE, solution):
        grouping_p = []
        p_num = list(GE.columns)
        for p in p_num:
            if p in solution[1][0]:
                grouping_p.append(1)
            else:
                grouping_p.append(2)
        grouping_p = pd.DataFrame(grouping_p,index = p_num)
        grouping_g = []
        g_num = list(GE.index)
        for g in g_num:
            if g in solution[0][0]:
                grouping_g.append(1)
            elif  g in solution[0][1]:
                grouping_g.append(2)
            else:
                grouping_g.append(3)
                
        grouping_g = pd.DataFrame(grouping_g,index = g_num)
        species = grouping_p[0]
        lut = {1: '#A52A2A', 2: '#7FFFD4'}
        row_colors = species.map(lut)
        species = grouping_g[0]
        lut = {1: '#A52A2A', 2: '#7FFFD4', 3:'#FAEBD7'}
        col_colors = species.map(lut)
        sns.clustermap(GE.T, row_colors=row_colors, col_colors = col_colors,figsize=(15, 10))
    
    def features(self, solution, GE, G, pos = None):
        genes1,genes2 = solution[0]
        patients1, patients2 = solution[1]
        
        means1 = list(np.mean(GE[patients1].loc[genes1],axis = 1)-np.mean(GE[patients2].loc[genes1],axis = 1).values)
        means2 = list(np.mean(GE[patients1].loc[genes2],axis = 1)-np.mean(GE[patients2].loc[genes2],axis = 1).values)
        G_small = nx.subgraph(G,genes1+genes2)
        
        fig = plt.figure(figsize=(15,10))
        vmin = -2
        vmax = 2
        if pos == None:
            pos = nx.spring_layout(G_small)
        ec = nx.draw_networkx_edges(G_small,pos)
        nc1 = nx.draw_networkx_nodes(G_small,nodelist =genes1, pos = pos,node_color=means1, node_size=200,alpha=1.0,
                                     vmin=vmin, vmax=vmax,node_shape = "^",cmap =plt.cm.PRGn)
        nc2 = nx.draw_networkx_nodes(G_small,nodelist =genes2, pos = pos,node_color=means2, node_size=200,
                                     alpha=1.0,
                                     vmin=vmin, vmax=vmax,node_shape = "o",cmap =plt.cm.PRGn)
        nx.draw_networkx_labels(G_small,pos)
        plt.colorbar(nc1)
        plt.axis('off')
        
        plt.show(block=False)
        plt.close(fig)
    

    
    
    def clean_net(self, gene_groups, patients_groups, clusters, L_g,G, GE, d_cut =2):    
        genes_components = []
        sizes = []
        for clust in range(clusters):
            group_g = gene_groups[clust]
            if clust == 0:
                not_clust = 1
            else:
                not_clust = 0
            if len(group_g)>=L_g:
                g = nx.subgraph(G,group_g)
                #we are taking only the biggest connected component
                comp_big = max(nx.connected_component_subgraphs(g), key=len)
                #measure the degree of each node in it
                dg = dict(nx.degree(comp_big))
                #separate those with d == 1 as nodes that we can kick out potentially 
                ones = [x for x in dg if dg[x]==1]
                nodes = list(comp_big.nodes)
                size_comp = len(nodes)
                #maximum # of nodes we can kick out 
                max_out = len(nodes)- L_g
                while max_out >0:
                    #measure the difference in the expression between two groups for d == 1 nodes
    
                    dif = np.mean(GE[patients_groups[clust]].loc[ones],axis = 1)-np.mean(GE[patients_groups[not_clust]].loc[ones],axis = 1)
                    dif = dif.sort_values()
                    #therefore we select the nodes with d == 1 and low difference
                    ones = list(dif[dif<1.5].index)
                    if len(ones)>0:
                        if len(ones)<=max_out:
                            outsiders = ones
                        else:
                            outsiders = list(ones)[:max_out]
         
                        nodes  = list(set(nodes) - set(outsiders))
                        g = nx.subgraph(G,nodes)
                        comp_big = max(nx.connected_component_subgraphs(g), key=len)
                        dg = dict(nx.degree(comp_big))
                        if d_cut ==1:
                            ones = [x for x in dg if (dg[x]==1)]
                        else:
                            ones = [x for x in dg if ((dg[x]==1) or (dg[x]==d_cut))]
                        nodes = list(comp_big.nodes)
                        size_comp = len(nodes)
                        max_out = len(nodes)- L_g
                    else:
                        max_out = 0
                        
                group_g = nodes
            elif len(group_g)>0:
                g = nx.subgraph(G,group_g)
                comp_big = max(nx.connected_component_subgraphs(g), key=len)
                nodes = list(comp_big.nodes)
                size_comp = len(nodes)
            else:
                size_comp = 0
                
            genes_components.append(group_g)
            sizes.append(size_comp)
        return genes_components, sizes


