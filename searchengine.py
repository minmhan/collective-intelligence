# -*- coding: utf-8 -*-
"""
Created on Mon Jun  6 21:49:28 2016

@author: minmhan
"""

import urllib
from urllib import request
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import sqlite3
import re

ignorewords = set(['the','of','to','and','a','in','is','it'])
class crawler:
    def __init__(self, dbname):
        self.con=sqlite3.connect(dbname)
    
    def __del__self(self):
        self.con.close()
        
    def dbcommit(self):
        self.con.commit()
    
    
    # Auxilliary function for getting an entry id and adding it if it's not present
    def getentryid(self,table,field,value,createnew=True):
        cur=self.con.execute("select rowid from %s where %s='%s'" % (table,field,value))
        res=cur.fetchone()
        if res==None:
            cur=self.con.execute("insert into %s (%s) values ('%s')" % (table,field,value))
            return cur.lastrowid
        else:
            return res[0]
    
    # Index an individual page
    def addtoindex(self,url,soup):
        if self.isindexed(url):
            return
        print('Indexing ', url)
        
        # Get the individual words
        text=self.gettextonly(soup)
        words=self.separatewords(text)
        
        # Get the URL id
        urlid=self.getentryid('urllist','url',url)
        
        # Link each word to this url
        for i in range(len(words)):
            word=words[i]
            if word in ignorewords:
                continue
            wordid=self.getentryid('wordlist','word',word)
            self.con.execute("insert into wordlocation(urlid,wordid,location) values (%d,%d,%d)" % (urlid,wordid,i))
        
    
    # Extract the text from an HTML page (no tags)
    def gettextonly(self,soup):
        v=soup.string
        if v==None:
            c=soup.contents
            resulttext=''
            for t in c:
                subtext=self.gettextonly(t)
                resulttext+=subtext+'\n'
            return resulttext
        else:
            return v.strip()
            
    
    # Separate the words by any non-whitespace character
    def separatewords(self,text):
        splitter=re.compile('\\W*')
        return [s.lower() for s in splitter.split(text) if s!='']
    
    # Return true if this url is already indexed
    def isindexed(self,url):
        u=self.con.execute("select rowid from urllist where url='%s'" % url).fetchone()
        if u!=None:
            #Check if it has actually been crawled
            v=self.con.execute('select * from wordlocation where urlid=%d' % u[0]).fetchone()
            if v!=None:
                return True
        return False
    
    
    
    # Add a link between two pages
    def addlinkref(self,urlFrom,urlTo,linkText):
        words=self.separatewords(linkText)
        fromid=self.getentryid('urllist','url',urlFrom)
        toid=self.getentryid('urllist','url',urlTo)
        if fromid==toid:
            return
        cur=self.con.execute("insert into link(fromid,toid) values (%d,%d)" %(fromid,toid))
        linkid=cur.lastrowid
        for word in words:
            if word in ignorewords:
                continue
            wordid=self.getentryid('wordlist','word',word)
            self.con.execute("insert into linkwords(linkid,wordid) values (%d,%d)" % (linkid,wordid))

    
    def crawl(self, pages, depth=2):
        for i in range(depth):
            newpages=set()
            for page in pages:
                try:
                    c=request.urlopen(page)
                except:
                    print('could not open %s' % page)
                    continue
                soup = BeautifulSoup(c.read())
                self.addtoindex(page,soup)
                
                links=soup('a')
                for link in links:
                    if('href' in dict(link.attrs)):
                        url= urljoin(page,link['href'])
                        if url.find("'")!=-1: continue
                        url=url.split('#')[0] #remove location portion
                        if url[0:4]=='http' and not self.isindexed(url):
                            newpages.add(url)
                        linkText=self.gettextonly(link)
                        self.addlinkref(page,url,linkText)
                            
                self.dbcommit()
                
            pages = newpages

    
    # Create the database tables
    def createindextables(self):
        self.con.execute('create table urllist(url)')
        self.con.execute('create table wordlist(word)')
        self.con.execute('create table wordlocation(urlid,wordid,location)')
        self.con.execute('create table link(fromid INTEGER,toid INTEGER)')
        self.con.execute('create table linkwords(wordid,linkid)')
        self.con.execute('create index wordidx on wordlist(word)')
        self.con.execute('create index urlidx on urllist(url)')
        self.con.execute('create index wordurlindex on wordlocation(wordid)')
        self.con.execute('create index urltoidx on link(toid)')
        self.con.execute('create index urlfromidx on link(fromid)')
        self.dbcommit()


class searcher:
    def __init__(self,dbname):
        self.con=sqlite3.connect(dbname)
        
    def __del__(self):
        self.con.close()
        
    def getmatchrows(self,q):
        # Strings to build the query
        fieldlist='w0.urlid'
        tablelist=''
        clauselist=''
        wordids=[]
        
        # Split the word by spaces
        words=q.split(' ')
        tablenumber=0
        
        for word in words:
            # Get the word ID
            wordrow=self.con.execute("select rowid from wordlist where word='%s'" % word).fetchone()
            if wordrow!=None:
                wordid=wordrow[0]
                wordids.append(wordid)
                if tablenumber>0:
                    tablelist+=','
                    clauselist+=' and '
                    clauselist+='w%d.urlid=w%d.urlid and ' % (tablenumber-1,tablenumber)
                fieldlist+=',w%d.location' % tablenumber
                tablelist+='wordlocation w%d' % tablenumber
                clauselist+='w%d.wordid=%d' % (tablenumber,wordid)
                tablenumber+=1
        
        # Create the query from the separate parts
        fullquery='select %s from %s where %s' % (fieldlist,tablelist,clauselist)
        cur=self.con.execute(fullquery)
        rows=[row for row in cur]
        
        return rows,wordids
        
        
    def getscoredlist(self,rows,wordids):
        totalscores=dict([(row[0],0) for row in rows])
                
        # This is where you'll later put the scoring functions
        weights=[(1.0,self.frequencyscore(rows)), (1.5, self.locationscore(rows))]
        
        for (weight,scores) in weights:
            for url in totalscores:
                totalscores[url]+=weight*scores[url]
                
        return totalscores
        
    def geturlname(self,id):
        return self.con.execute("select url from urllist where rowid=%d" % id).fetchone()[0]


    def query(self,q):
        rows,wordids=self.getmatchrows(q)
        scores=self.getscoredlist(rows,wordids)
        rankedscores=sorted([(score,url) for (url,score) in scores.items()],reverse=1)
        for (score,urlid) in rankedscores[0:10]:
            print('{0:f}   {1}'.format(score,self.geturlname(urlid)))


    def normalizescores(self,scores,smallIsBetter=0):
        vsmall=0.00001 # Avoid division by zero errors
        if smallIsBetter:
            minscore=min(scores.values())
            return dict([(u,float(minscore)/max(vsmall,l)) for (u,l) in scores.items()])
        else:
            maxscore=max(scores.values())
            if maxscore==0:
                maxscore=vsmall
            return dict([(u,float(c)/maxscore) for (u,c) in scores.items()])
                
        

    def frequencyscore(self,rows):
        counts=dict([row[0],0] for row in rows)
        #print(counts)
        for row in rows:
            counts[row[0]] +=1
        return self.normalizescores(counts)
        
    def locationscore(self,rows):
        locations=dict([(row[0],1000000) for row in rows])
        for row in rows:
            loc=sum(row[1:])
            if loc<locations[row[0]]:
                locations[row[0]]=loc
        
        return self.normalizescores(locations,smallIsBetter=1)
        
    def distancescore(self,rows):
        pass
        

pagelist=['http://it-ebooks.info']
c = crawler('searchindex.db')
#c.createindextables()
#c.crawl(pagelist)
#print([row for row in c.con.execute('select rowid from wordlocation where wordid=1')])
e=searcher('searchindex.db')
#print(e.getmatchrows('python programming why'))
e.query('android')

















