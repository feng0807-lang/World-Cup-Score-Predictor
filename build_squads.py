"""Build squads.json for the 2026 World Cup from fetched roster data.

Roster data (player number / position / name) was fetched from the Wikipedia
"2026 FIFA World Cup squads" article. This script parses it, assigns each
player a rating derived from the team's Elo, picks a sensible default
starting XI (4-3-3 by rating), and writes squads.json in the format the
dashboard expects.

Run once:  python build_squads.py
"""

from __future__ import annotations

import json
import random
import re

import teams as teams_mod

POS_MAP = {"GK": "GK", "DF": "DEF", "MF": "MID", "FW": "FWD"}

# Raw rosters keyed by the canonical team name used in teams.py.
RAW: dict[str, str] = {
"Mexico": """
1 GK Raúl Rangel
2 DF Jorge Sánchez
3 DF César Montes
4 DF Edson Álvarez
5 DF Johan Vásquez
6 MF Érik Lira
7 MF Luis Romo
8 MF Álvaro Fidalgo
9 FW Raúl Jiménez
10 FW Alexis Vega
11 FW Santiago Giménez
12 GK Carlos Acevedo
13 GK Guillermo Ochoa
14 FW Armando González
15 DF Israel Reyes
16 FW Julián Quiñones
17 MF Orbelín Pineda
18 MF Obed Vargas
19 MF Gilberto Mora
20 DF Mateo Chávez
21 FW César Huerta
22 FW Guillermo Martínez
23 DF Jesús Gallardo
24 MF Luis Chávez
25 FW Roberto Alvarado
26 MF Brian Gutiérrez
""",
"South Africa": """
1 GK Ronwen Williams
2 DF Thabang Matuludi
3 DF Khulumani Ndamane
4 MF Teboho Mokoena
5 MF Thalente Mbatha
6 DF Aubrey Modiba
7 FW Oswin Appollis
8 FW Tshepang Moremi
9 FW Lyle Foster
10 FW Relebohile Mofokeng
11 MF Themba Zwane
12 FW Thapelo Maseko
13 MF Sphephelo Sithole
14 DF Mbekezeli Mbokazi
15 FW Iqraam Rayners
16 GK Sipho Chaine
17 FW Evidence Makgopa
18 DF Samukele Kabini
19 DF Nkosinathi Sibisi
20 DF Khuliso Mudau
21 DF Ime Okon
22 GK Ricardo Goss
23 MF Jayden Adams
24 DF Olwethu Makhanya
25 FW Kamogelo Sebelebele
26 DF Bradley Cross
""",
"South Korea": """
1 GK Kim Seung-gyu
2 DF Lee Han-beom
3 MF Lee Gi-hyuk
4 DF Kim Min-jae
5 DF Kim Tae-hyeon
6 MF Hwang In-beom
7 FW Son Heung-min
8 MF Paik Seung-ho
9 FW Cho Gue-sung
10 MF Lee Jae-sung
11 MF Hwang Hee-chan
12 GK Song Bum-keun
13 DF Lee Tae-seok
14 DF Cho Wi-je
15 DF Kim Moon-hwan
16 DF Park Jin-seob
17 MF Bae Jun-ho
18 FW Oh Hyeon-gyu
19 MF Lee Kang-in
20 MF Yang Hyun-jun
21 GK Jo Hyeon-woo
22 DF Seol Young-woo
23 DF Jens Castrop
24 MF Kim Jin-gyu
25 MF Eom Ji-sung
26 MF Lee Dong-gyeong
""",
"Czechia": """
1 GK Matěj Kovář
2 DF David Zima
3 DF Tomáš Holeš
4 DF Robin Hranáč
5 DF Vladimír Coufal
6 DF Štěpán Chaloupek
7 DF Ladislav Krejčí
8 MF Vladimír Darida
9 FW Adam Hložek
10 FW Patrik Schick
11 FW Jan Kuchta
12 MF Lukáš Červ
13 FW Mojmír Chytil
14 DF David Jurásek
15 FW Pavel Šulc
16 GK Jindřich Staněk
17 MF Lukáš Provod
18 MF Michal Sadílek
19 FW Tomáš Chorý
20 DF Jaroslav Zelený
21 DF David Douděra
22 MF Tomáš Souček
23 GK Lukáš Horníček
24 MF Alexandr Sojka
25 MF Hugo Sochůrek
26 FW Denis Višinský
""",
"Canada": """
1 GK Dayne St. Clair
2 DF Alistair Johnston
3 DF Alfie Jones
4 DF Luc de Fougerolles
5 DF Joel Waterman
6 MF Mathieu Choinière
7 MF Stephen Eustáquio
8 MF Ismaël Koné
9 FW Cyle Larin
10 FW Jonathan David
11 MF Liam Millar
12 FW Tani Oluwaseyi
13 DF Derek Cornelius
14 MF Jacob Shaffelburg
15 DF Moïse Bombito
16 GK Maxime Crépeau
17 FW Tajon Buchanan
18 GK Owen Goodman
19 DF Alphonso Davies
20 FW Ali Ahmed
21 MF Jonathan Osorio
22 DF Richie Laryea
23 DF Niko Sigur
24 FW Promise David
25 MF Nathan Saliba
""",
"Bosnia and Herzegovina": """
1 GK Nikola Vasilj
2 DF Nihad Mujakić
3 DF Dennis Hadžikadunić
4 DF Tarik Muharemović
5 DF Sead Kolašinac
6 MF Benjamin Tahirović
7 DF Amar Dedić
8 MF Armin Gigović
9 FW Samed Baždar
10 FW Ermedin Demirović
11 FW Edin Džeko
12 GK Mladen Jurkas
13 MF Ivan Bašić
14 MF Ivan Šunjić
15 MF Amar Memić
16 MF Amir Hadžiahmetović
17 MF Dženis Burnić
18 DF Nikola Katić
19 FW Kerim Alajbegović
20 FW Esmir Bajraktarević
21 DF Stjepan Radeljić
22 GK Martin Zlomislić
23 FW Haris Tabaković
24 DF Nidal Čelik
25 FW Jovo Lukić
26 MF Ermin Mahmić
""",
"Qatar": """
1 GK Mahmud Abunada
2 DF Pedro Miguel
3 DF Lucas Mendes
4 DF Issa Laye
5 DF Jassem Gaber
6 MF Abdulaziz Hatem
7 FW Ahmed Alaaeldin
8 FW Edmilson Junior
9 FW Mohammed Muntari
10 FW Hassan Al-Haydos
11 FW Akram Afif
12 MF Karim Boudiaf
13 DF Ayoub Al-Oui
14 DF Homam Ahmed
15 FW Yusuf Abdurisag
16 DF Boualem Khoukhi
17 MF Ahmed Al-Ganehi
18 DF Sultan Al-Brake
19 FW Almoez Ali
20 MF Ahmed Fathy
21 GK Salah Zakaria
22 GK Meshaal Barsham
23 MF Assim Madibo
24 FW Tahsin Jamshid
25 DF Al-Hashmi Al-Hussain
26 FW Mohamed Manai
""",
"Switzerland": """
1 GK Gregor Kobel
2 DF Miro Muheim
3 DF Silvan Widmer
4 DF Nico Elvedi
5 DF Manuel Akanji
6 MF Denis Zakaria
7 FW Breel Embolo
8 MF Remo Freuler
9 MF Johan Manzambi
10 MF Granit Xhaka
11 FW Dan Ndoye
12 GK Yvon Mvogo
13 DF Ricardo Rodriguez
14 MF Ardon Jashari
15 MF Djibril Sow
16 FW Christian Fassnacht
17 FW Rubén Vargas
18 DF Eray Cömert
19 FW Noah Okafor
20 MF Michel Aebischer
21 GK Marvin Keller
22 MF Fabian Rieder
23 FW Zeki Amdouni
24 DF Aurèle Amenda
25 DF Luca Jaquez
26 FW Cedric Itten
""",
"Brazil": """
1 GK Alisson
2 DF Wesley
3 DF Gabriel Magalhães
4 DF Marquinhos
5 MF Casemiro
6 DF Alex Sandro
7 FW Vinícius Júnior
8 MF Bruno Guimarães
9 FW Matheus Cunha
10 FW Neymar
11 FW Raphinha
12 GK Weverton
13 DF Danilo Luiz
14 DF Bremer
15 DF Léo Pereira
16 DF Douglas Santos
17 MF Fabinho
18 MF Danilo Santos
19 FW Endrick
20 MF Lucas Paquetá
21 FW Luiz Henrique
22 FW Gabriel Martinelli
23 GK Ederson
24 DF Roger Ibáñez
25 FW Igor Thiago
26 FW Rayan
""",
"Morocco": """
1 GK Yassine Bounou
2 DF Achraf Hakimi
3 DF Noussair Mazraoui
4 MF Sofyan Amrabat
5 DF Nayef Aguerd
6 MF Ayyoub Bouaddi
7 MF Chemsdine Talbi
8 MF Azzedine Ounahi
9 FW Soufiane Rahimi
10 FW Brahim Díaz
11 MF Ismael Saibari
12 GK Munir Mohamedi
13 DF Zakaria El Ouahdi
14 DF Issa Diop
15 MF Samir El Mourabet
16 MF Gessime Yassine
17 FW Abde Ezzalzouli
18 DF Chadi Riad
19 DF Youssef Belammari
20 FW Ayoub El Kaabi
21 FW Ayoube Amaimouni
22 GK Ahmed Reda Tagnaouti
23 MF Bilal El Khannouss
24 MF Neil El Aynaoui
25 DF Redouane Halhal
26 DF Anass Salah-Eddine
""",
"Haiti": """
1 GK Johny Placide
2 DF Carlens Arcus
3 DF Keeto Thermoncy
4 DF Ricardo Adé
5 DF Hannes Delcroix
6 MF Carl Sainté
7 FW Derrick Etienne Jr.
8 DF Martin Expérience
9 FW Duckens Nazon
10 MF Jean-Ricner Bellegarde
11 FW Louicius Deedson
12 GK Alexandre Pierre
13 DF Duke Lacroix
14 MF Leverton Pierre
15 FW Ruben Providence
16 FW Lenny Joseph
17 MF Danley Jean Jacques
18 FW Wilson Isidor
19 FW Yassin Fortuné
20 FW Frantzdy Pierrot
21 FW Josué Casimir
22 DF Jean-Kévin Duverne
23 GK Josué Duverger
24 DF Wilguens Paugain
25 MF Dominique Simon
26 MF Woodensky Pierre
""",
"Scotland": """
1 GK Angus Gunn
2 DF Aaron Hickey
3 DF Andy Robertson
4 MF Scott McTominay
5 DF Grant Hanley
6 DF Kieran Tierney
7 MF John McGinn
8 MF Tyler Fletcher
9 FW Lyndon Dykes
10 FW Ché Adams
11 MF Ryan Christie
12 GK Liam Kelly
13 DF Jack Hendry
14 FW Ross Stewart
15 DF John Souttar
16 DF Dominic Hyam
17 FW Ben Gannon-Doak
18 FW George Hirst
19 MF Lewis Ferguson
20 FW Lawrence Shankland
21 GK Craig Gordon
22 DF Nathan Patterson
23 MF Kenny McLean
24 DF Anthony Ralston
25 FW Findlay Curtis
26 DF Scott McKenna
""",
"United States": """
1 GK Matt Turner
2 DF Sergiño Dest
3 DF Chris Richards
4 MF Tyler Adams
5 DF Antonee Robinson
6 DF Auston Trusty
7 MF Giovanni Reyna
8 MF Weston McKennie
9 FW Ricardo Pepi
10 FW Christian Pulisic
11 FW Brenden Aaronson
12 DF Miles Robinson
13 DF Tim Ream
14 MF Sebastian Berhalter
15 MF Cristian Roldan
16 DF Alex Freeman
17 MF Malik Tillman
18 DF Maximilian Arfsten
19 FW Haji Wright
20 FW Folarin Balogun
21 FW Timothy Weah
22 DF Mark McKenzie
23 DF Joe Scally
24 GK Matt Freese
25 GK Chris Brady
26 FW Alejandro Zendejas
""",
"Paraguay": """
1 GK Gatito Fernández
2 DF Gustavo Velázquez
3 DF Omar Alderete
4 DF Juan José Cáceres
5 DF Fabián Balbuena
6 DF Junior Alonso
7 MF Ramón Sosa
8 MF Diego Gómez
9 FW Antonio Sanabria
10 MF Miguel Almirón
11 MF Maurício
12 GK Orlando Gill
13 DF José Canale
14 MF Andrés Cubas
15 DF Gustavo Gómez
16 MF Damián Bobadilla
17 FW Kaku
18 FW Álex Arce
19 FW Julio Enciso
20 MF Braian Ojeda
21 FW Gabriel Ávalos
22 GK Gastón Olveira
23 MF Matías Galarza
24 MF Gustavo Caballero
25 FW Isidro Pitta
26 DF Alexandro Maidana
""",
"Australia": """
1 GK Mathew Ryan
2 DF Miloš Degenek
3 DF Alessandro Circati
4 DF Jacob Italiano
5 DF Jordan Bos
6 DF Jason Geria
7 FW Mathew Leckie
8 MF Connor Metcalfe
9 FW Mohamed Touré
10 FW Ajdin Hrustic
11 FW Awer Mabil
12 GK Paul Izzo
13 MF Aiden O'Neill
14 MF Cammy Devlin
15 DF Kai Trewin
16 DF Aziz Behich
17 FW Nestory Irankunda
18 GK Patrick Beach
19 DF Harry Souttar
20 FW Cristian Volpato
21 DF Cameron Burgess
22 MF Jackson Irvine
23 FW Nishan Velupillay
24 MF Paul Okon-Engstler
25 DF Lucas Herrington
26 FW Tete Yengi
""",
"Turkey": """
1 GK Mert Günok
2 DF Zeki Çelik
3 DF Merih Demiral
4 DF Çağlar Söyüncü
5 MF Salih Özcan
6 MF Orkun Kökçü
7 FW Kerem Aktürkoglu
8 FW Arda Güler
9 FW Deniz Gül
10 MF Hakan Çalhanoğlu
11 FW Kenan Yıldız
12 GK Altay Bayındır
13 DF Eren Elmalı
14 DF Abdülkerim Bardakcı
15 DF Ozan Kabak
16 MF İsmail Yüksek
17 FW İrfan Can Kahveci
18 DF Mert Müldür
19 FW Yunus Akgün
20 DF Ferdi Kadıoğlu
21 FW Barış Alper Yılmaz
22 MF Kaan Ayhan
23 GK Uğurcan Çakır
24 FW Oğuz Aydın
25 DF Samet Akaydin
26 FW Can Uzun
""",
"Germany": """
1 GK Manuel Neuer
2 DF Antonio Rüdiger
3 DF Waldemar Anton
4 DF Jonathan Tah
5 MF Aleksandar Pavlović
6 DF Joshua Kimmich
7 FW Kai Havertz
8 MF Leon Goretzka
9 MF Jamie Leweling
10 MF Jamal Musiala
11 FW Nick Woltemade
12 GK Oliver Baumann
13 MF Pascal Groß
14 FW Maximilian Beier
15 DF Nico Schlotterbeck
16 MF Angelo Stiller
17 MF Florian Wirtz
18 DF Nathaniel Brown
19 MF Leroy Sané
20 MF Nadiem Amiri
21 GK Alexander Nübel
22 DF David Raum
23 MF Felix Nmecha
24 DF Malick Thiaw
25 MF Lennart Karl
26 FW Deniz Undav
""",
"Curacao": """
1 GK Eloy Room
2 DF Shurandy Sambo
3 DF Juriën Gaari
4 DF Roshon van Eijma
5 DF Sherel Floranus
6 MF Godfried Roemeratoe
7 MF Juninho Bacuna
8 MF Livano Comenencia
9 FW Jürgen Locadia
10 MF Leandro Bacuna
11 FW Jeremy Antonisse
12 FW Sontje Hansen
13 FW Tyrese Noslin
14 FW Kenji Gorré
15 MF Ar'jany Martha
16 FW Jearl Margaritha
17 FW Brandley Kuwas
18 DF Armando Obispo
19 FW Gervane Kastaneer
20 DF Joshua Brenet
21 MF Tahith Chong
22 MF Kevin Felida
23 DF Riechedly Bazoer
24 DF Deveron Fonville
25 GK Tyrick Bodak
26 GK Trevor Doornbusch
""",
"Ivory Coast": """
1 GK Yahia Fofana
2 DF Ousmane Diomande
3 DF Ghislain Konan
4 MF Jean Michaël Seri
5 DF Wilfried Singo
6 MF Seko Fofana
7 DF Odilon Kossounou
8 MF Franck Kessié
9 FW Ange-Yoan Bonny
10 FW Simon Adingra
11 FW Yan Diomande
12 FW Elye Wahi
13 DF Christopher Opéri
14 FW Oumar Diakité
15 FW Amad Diallo
16 GK Mohamed Koné
17 DF Guéla Doué
18 MF Ibrahim Sangaré
19 FW Nicolas Pépé
20 DF Emmanuel Agbadou
21 DF Evan Ndicka
22 FW Evann Guessand
23 GK Alban Lafont
24 FW Bazoumana Touré
25 MF Parfait Guiagon
26 MF Christ Inao Oulai
""",
"Ecuador": """
1 GK Hernán Galíndez
2 DF Félix Torres
3 DF Piero Hincapié
4 DF Joel Ordóñez
5 MF Jordy Alcívar
6 DF Willian Pacho
7 DF Pervis Estupiñán
8 MF Anthony Valencia
9 FW John Yeboah
10 MF Kendry Páez
11 FW Kevin Rodríguez
12 GK Moisés Ramírez
13 FW Enner Valencia
14 MF Alan Minda
15 MF Pedro Vite
16 FW Jordy Caicedo
17 DF Ángelo Preciado
18 MF Denil Castillo
19 FW Gonzalo Plata
20 FW Nilson Angulo
21 MF Alan Franco
22 GK Gonzalo Valle
23 MF Moisés Caicedo
24 FW Jeremy Arévalo
25 DF Jackson Porozo
26 DF Yaimar Medina
""",
"Netherlands": """
1 GK Bart Verbruggen
2 DF Jurriën Timber
3 MF Marten de Roon
4 DF Virgil van Dijk
5 DF Nathan Aké
6 DF Jan Paul van Hecke
7 MF Justin Kluivert
8 MF Ryan Gravenberch
9 FW Wout Weghorst
10 FW Memphis Depay
11 FW Cody Gakpo
12 DF Mats Wieffer
13 GK Robin Roefs
14 MF Tijjani Reijnders
15 DF Micky van de Ven
16 MF Guus Til
17 FW Noa Lang
18 FW Donyell Malen
19 FW Brian Brobbey
20 MF Teun Koopmeiners
21 MF Frenkie de Jong
22 DF Denzel Dumfries
23 GK Mark Flekken
24 FW Crysencio Summerville
25 DF Jorrel Hato
26 MF Quinten Timber
""",
"Japan": """
1 GK Zion Suzuki
2 DF Yukinari Sugawara
3 DF Shōgo Taniguchi
4 DF Kō Itakura
5 DF Yūto Nagatomo
6 MF Wataru Endo
7 MF Ao Tanaka
8 MF Takefusa Kubo
9 FW Keisuke Gotō
10 MF Ritsu Dōan
11 MF Daizen Maeda
12 GK Keisuke Ōsako
13 MF Keito Nakamura
14 MF Junya Itō
15 MF Daichi Kamada
16 DF Tsuyoshi Watanabe
17 MF Yuito Suzuki
18 FW Ayase Ueda
19 FW Kōki Ogawa
20 DF Ayumu Seko
21 DF Hiroki Itō
22 DF Takehiro Tomiyasu
23 GK Tomoki Hayakawa
24 MF Kaishū Sano
25 DF Junnosuke Suzuki
26 FW Kento Shiogai
""",
"Sweden": """
1 GK Jacob Widell Zetterström
2 DF Gustaf Lagerbielke
3 DF Victor Lindelöf
4 DF Isak Hien
5 DF Gabriel Gudmundsson
6 DF Herman Johansson
7 MF Lucas Bergvall
8 DF Daniel Svensson
9 FW Alexander Isak
10 MF Benjamin Nygren
11 FW Anthony Elanga
12 GK Viktor Johansson
13 MF Ken Sema
14 DF Hjalmar Ekdal
15 DF Carl Starfelt
16 MF Jesper Karlström
17 FW Viktor Gyökeres
18 MF Yasin Ayari
19 MF Mattias Svanberg
20 DF Eric Smith
21 DF Alexander Bernhardsson
22 MF Besfort Zeneli
23 GK Kristoffer Nordfeldt
24 DF Elliot Stroud
25 FW Gustaf Nilsson
26 FW Taha Ali
""",
"Tunisia": """
1 GK Mouhib Chamakh
2 DF Ali Abdi
3 DF Montassar Talbi
4 DF Omar Rekik
5 DF Adem Arous
6 DF Dylan Bronn
7 FW Elias Achouri
8 FW Elias Saad
9 FW Hazem Mastouri
10 MF Hannibal Mejbri
11 MF Ismaël Gharbi
12 DF Mortadha Ben Ouanes
13 MF Rani Khedira
14 MF Khalil Ayari
15 MF Hadj Mahmoud
16 GK Aymen Dahmen
17 MF Ellyes Skhiri
18 FW Rayan Elloumi
19 FW Firas Chaouat
20 DF Yan Valery
21 DF Mohamed Amine Ben Hamida
22 GK Sabri Ben Hessen
23 DF Moutaz Neffati
24 DF Raed Chikhaoui
25 MF Anis Ben Slimane
26 MF Sebastian Tounekti
""",
"Belgium": """
1 GK Thibaut Courtois
2 DF Zeno Debast
3 DF Arthur Theate
4 DF Brandon Mechele
5 DF Maxim De Cuyper
6 MF Axel Witsel
7 MF Kevin De Bruyne
8 MF Youri Tielemans
9 FW Romelu Lukaku
10 FW Leandro Trossard
11 FW Jérémy Doku
12 GK Senne Lammens
13 GK Mike Penders
14 FW Dodi Lukébakio
15 DF Thomas Meunier
16 DF Koni De Winter
17 FW Charles De Ketelaere
18 DF Joaquin Seys
19 MF Diego Moreira
20 MF Hans Vanaken
21 DF Timothy Castagne
22 MF Alexis Saelemaekers
23 MF Nicolas Raskin
24 MF Amadou Onana
25 DF Nathan Ngoy
26 FW Matias Fernandez-Pardo
""",
"Egypt": """
1 GK Mohamed El Shenawy
2 DF Yasser Ibrahim
3 DF Mohamed Hany
4 DF Hossam Abdelmaguid
5 DF Ramy Rabia
6 DF Mohamed Abdelmonem
7 FW Trézéguet
8 MF Emam Ashour
9 FW Hamza Abdelkarim
10 FW Mohamed Salah
11 MF Mostafa Ziko
12 FW Haissem Hassan
13 DF Ahmed Fatouh
14 MF Hamdy Fathy
15 DF Karim Hafez
16 GK El Mahdy Soliman
17 MF Mohanad Lasheen
18 MF Nabil Emad
19 MF Marwan Attia
20 FW Ibrahim Adel
21 MF Mahmoud Saber
22 FW Omar Marmoush
23 GK Mostafa Shobeir
24 DF Tarek Alaa
25 FW Zizo
26 GK Mohamed Alaa
""",
"Iran": """
1 GK Alireza Beiranvand
2 DF Saleh Hardani
3 DF Ehsan Hajsafi
4 DF Shojae Khalilzadeh
5 DF Milad Mohammadi
6 MF Saeid Ezatolahi
7 MF Alireza Jahanbakhsh
8 MF Mohammad Mohebi
9 FW Mehdi Taremi
10 FW Mehdi Ghayedi
11 FW Ali Alipour
12 GK Payam Niazmand
13 DF Hossein Kanaanizadegan
14 MF Saman Ghoddos
15 MF Rouzbeh Cheshmi
16 MF Mehdi Torabi
17 DF Aria Yousefi
18 FW Amirhossein Hosseinzadeh
19 DF Ali Nemati
20 FW Shahriyar Moghanlou
21 MF Mohammad Ghorbani
22 GK Hossein Hosseini
23 DF Ramin Rezaeian
24 FW Dennis Eckert
25 DF Danial Eiri
26 MF Amirmohammad Razzaghinia
""",
"New Zealand": """
1 GK Max Crocombe
2 DF Tim Payne
3 DF Francis de Vries
4 DF Tyler Bindon
5 DF Michael Boxall
6 MF Joe Bell
7 MF Matthew Garbett
8 MF Marko Stamenić
9 FW Chris Wood
10 MF Sarpreet Singh
11 MF Elijah Just
12 GK Alex Paulsen
13 DF Liberato Cacace
14 MF Alex Rufer
15 DF Nando Pijnaker
16 DF Finn Surman
17 FW Kosta Barbarouses
18 FW Ben Waine
19 MF Ben Old
20 MF Callum McCowatt
21 FW Jesse Randall
22 GK Michael Woud
23 MF Ryan Thomas
24 DF Callan Elliot
25 MF Lachlan Bayliss
26 DF Tommy Smith
""",
"Spain": """
1 GK David Raya
2 DF Marc Pubill
3 DF Álex Grimaldo
4 DF Eric García
5 DF Marcos Llorente
6 MF Mikel Merino
7 FW Ferran Torres
8 MF Fabián Ruiz
9 MF Gavi
10 FW Dani Olmo
11 FW Yéremy Pino
12 DF Pedro Porro
13 GK Joan Garcia
14 DF Aymeric Laporte
15 MF Álex Baena
16 MF Rodri
17 FW Nico Williams
18 MF Martín Zubimendi
19 FW Lamine Yamal
20 MF Pedri
21 FW Mikel Oyarzabal
22 DF Pau Cubarsí
23 GK Unai Simón
24 DF Marc Cucurella
25 FW Víctor Muñoz
26 FW Borja Iglesias
""",
"Cape Verde": """
1 GK Vozinha
2 DF Stopira
3 DF Diney
4 DF Roberto Lopes
5 DF Logan Costa
6 MF Kevin Pina
7 MF Jovane Cabral
8 MF João Paulo
9 FW Gilson Benchimol
10 MF Jamiro Monteiro
11 MF Garry Rodrigues
12 GK Mário Rosa
13 DF Sidny Lopes Cabral
14 MF Deroy Duarte
15 MF Laros Duarte
16 MF Yannick Semedo
17 MF Willy Semedo
18 MF Telmo Arcanjo
19 FW Dailon Livramento
20 FW Ryan Mendes
21 MF Nuno da Costa
22 DF Steven Moreira
23 GK CJ dos Santos
24 DF Wagner Pina
25 DF Kelvin Pires
26 MF Hélio Varela
""",
"Saudi Arabia": """
1 GK Nawaf Al-Aqidi
2 DF Ali Majrashi
3 DF Ali Lajami
4 DF Abdulelah Al-Amri
5 DF Hassan Al-Tambakti
6 MF Nasser Al-Dawsari
7 MF Musab Al-Juwayr
8 FW Ayman Yahya
9 FW Firas Al-Buraikan
10 FW Salem Al-Dawsari
11 FW Saleh Al-Shehri
12 DF Saud Abdulhamid
13 DF Nawaf Boushal
14 DF Hassan Kadesh
15 MF Abdullah Al-Khaibari
16 MF Ziyad Al-Johani
17 FW Khalid Al-Ghannam
18 MF Alaa Al-Hejji
19 FW Abdullah Al-Hamdan
20 FW Sultan Mandash
21 GK Mohammed Al-Owais
22 GK Ahmed Al-Kassar
23 MF Mohamed Kanno
24 DF Moteb Al-Harbi
25 DF Jehad Thakri
26 DF Mohammed Abu Al-Shamat
""",
"Uruguay": """
1 GK Sergio Rochet
2 DF José María Giménez
3 DF Sebastián Cáceres
4 DF Ronald Araújo
5 MF Manuel Ugarte
6 MF Rodrigo Bentancur
7 MF Nicolás de la Cruz
8 MF Federico Valverde
9 FW Darwin Núñez
10 MF Giorgian de Arrascaeta
11 FW Facundo Pellistri
12 GK Santiago Mele
13 DF Guillermo Varela
14 MF Agustín Canobbio
15 MF Emiliano Martínez
16 DF Mathías Olivera
17 DF Matías Viña
18 FW Brian Rodríguez
19 FW Rodrigo Aguirre
20 MF Maximiliano Araújo
21 FW Federico Viñas
22 MF Joaquín Piquerez
23 GK Fernando Muslera
24 DF Santiago Bueno
25 MF Juan Manuel Sanabria
26 MF Rodrigo Zalazar
""",
"France": """
1 GK Brice Samba
2 DF Malo Gusto
3 DF Lucas Digne
4 DF Dayot Upamecano
5 DF Jules Koundé
6 MF Manu Koné
7 FW Ousmane Dembélé
8 MF Aurélien Tchouaméni
9 FW Marcus Thuram
10 FW Kylian Mbappé
11 FW Michael Olise
12 FW Bradley Barcola
13 MF N'Golo Kanté
14 MF Adrien Rabiot
15 DF Ibrahima Konaté
16 GK Mike Maignan
17 DF William Saliba
18 MF Warren Zaïre-Emery
19 DF Théo Hernandez
20 FW Désiré Doué
21 DF Lucas Hernandez
22 FW Jean-Philippe Mateta
23 GK Robin Risser
24 MF Rayan Cherki
25 MF Maghnes Akliouche
26 DF Maxence Lacroix
""",
"Senegal": """
1 GK Yehvann Diouf
2 DF Mamadou Sarr
3 DF Kalidou Koulibaly
4 DF Abdoulaye Seck
5 MF Idrissa Gueye
6 MF Pathé Ciss
7 FW Assane Diao
8 MF Lamine Camara
9 FW Bamba Dieng
10 FW Sadio Mané
11 FW Nicolas Jackson
12 FW Cherif Ndiaye
13 FW Iliman Ndiaye
14 DF Ismail Jakobs
15 DF Krépin Diatta
16 GK Édouard Mendy
17 MF Pape Matar Sarr
18 FW Ismaïla Sarr
19 DF Moussa Niakhaté
20 FW Ibrahim Mbaye
21 MF Habib Diarra
22 MF Bara Sapoko Ndiaye
23 GK Mory Diaw
24 DF Antoine Mendy
25 DF El Hadji Malick Diouf
26 MF Pape Gueye
""",
"Iraq": """
1 GK Fahad Talib
2 DF Rebin Sulaka
3 DF Hussein Ali
4 DF Zaid Tahseen
5 DF Akam Hashim
6 DF Manaf Younis
7 MF Youssef Amyn
8 MF Ibrahim Bayesh
9 FW Ali Al-Hamadi
10 FW Mohanad Ali
11 FW Ahmed Qasem
12 GK Jalal Hassan
13 FW Ali Yousif
14 MF Zidane Iqbal
15 DF Ahmed Yahya
16 MF Amir Al-Ammari
17 FW Ali Jasim
18 FW Aymen Hussein
19 MF Kevin Yakob
20 MF Aimar Sher
21 FW Marko Farji
22 GK Ahmed Basil
23 DF Merchas Doski
24 MF Zaid Ismail
25 DF Mustafa Saadoon
26 DF Frans Putros
""",
"Norway": """
1 GK Ørjan Nyland
2 MF Morten Thorsby
3 DF Kristoffer Ajer
4 DF Leo Østigård
5 DF David Møller Wolfe
6 MF Patrick Berg
7 FW Alexander Sørloth
8 MF Sander Berge
9 FW Erling Haaland
10 MF Martin Ødegaard
11 FW Jørgen Strand Larsen
12 GK Sander Tangvik
13 GK Egil Selvik
14 MF Fredrik Aursnes
15 DF Fredrik André Bjørkan
16 DF Marcus Holmgren Pedersen
17 DF Torbjørn Heggem
18 MF Kristian Thorstvedt
19 MF Thelo Aasgaard
20 FW Antonio Nusa
21 MF Andreas Schjelderup
22 MF Oscar Bobb
23 MF Jens Petter Hauge
24 DF Sondre Langås
25 DF Henrik Falchener
26 FW Julian Ryerson
""",
"Algeria": """
1 GK Melvin Mastil
2 DF Aïssa Mandi
3 DF Achref Abada
4 DF Mohamed Amine Tougai
5 DF Zineddine Belaïd
6 MF Ramiz Zerrouki
7 FW Riyad Mahrez
8 MF Houssem Aouar
9 FW Amine Gouiri
10 MF Farès Chaïbi
11 FW Anis Hadj Moussa
12 FW Nadhir Benbouali
13 DF Jaouen Hadjam
14 MF Hicham Boudaoui
15 DF Rayan Aït-Nouri
16 GK Oussama Benbot
17 DF Rafik Belghali
18 FW Mohamed Amoura
19 MF Nabil Bentaleb
20 FW Adil Boulbina
21 DF Ramy Bensebaini
22 MF Ibrahim Maza
23 GK Luca Zidane
24 MF Yacine Titraoui
25 FW Farès Ghedjemis
26 DF Samir Chergui
""",
"Argentina": """
1 GK Juan Musso
2 DF Leonardo Balerdi
3 DF Nicolás Tagliafico
4 DF Gonzalo Montiel
5 MF Leandro Paredes
6 DF Lisandro Martínez
7 MF Rodrigo De Paul
8 MF Valentín Barco
9 FW Julián Alvarez
10 FW Lionel Messi
11 MF Giovani Lo Celso
12 GK Gerónimo Rulli
13 DF Cristian Romero
14 MF Exequiel Palacios
15 MF Nicolás González
16 FW Thiago Almada
17 FW Giuliano Simeone
18 FW Nico Paz
19 DF Nicolás Otamendi
20 MF Alexis Mac Allister
21 FW José Manuel López
22 FW Lautaro Martínez
23 GK Emiliano Martínez
24 MF Enzo Fernández
25 DF Facundo Medina
26 DF Nahuel Molina
""",
"Austria": """
1 GK Alexander Schlager
2 DF David Affengruber
3 DF Kevin Danso
4 MF Xaver Schlager
5 DF Stefan Posch
6 MF Nicolas Seiwald
7 FW Marko Arnautović
8 DF David Alaba
9 MF Marcel Sabitzer
10 MF Florian Grillitsch
11 FW Michael Gregoritsch
12 GK Florian Wiegele
13 GK Patrick Pentz
14 FW Saša Kalajdžić
15 DF Philipp Lienhart
16 DF Phillipp Mwene
17 MF Carney Chukwuemeka
18 MF Romano Schmid
20 MF Konrad Laimer
21 FW Patrick Wimmer
22 MF Alexander Prass
23 DF Marco Friedl
24 MF Paul Wanner
25 DF Michael Svoboda
26 MF Alessandro Schöpf
""",
"Jordan": """
1 GK Yazeed Abulaila
2 DF Mohammad Abu Hashish
3 DF Abdallah Nasib
4 DF Husam Abu Dahab
5 DF Yazan Al-Arab
6 MF Amer Jamous
7 FW Mohammad Abu Zrayq
8 MF Noor Al-Rawabdeh
9 FW Ali Olwan
10 FW Musa Al-Taamari
11 FW Odeh Al-Fakhouri
12 GK Nour Bani Attiah
13 FW Mahmoud Al-Mardi
14 MF Rajaei Ayed
15 MF Ibrahim Sadeh
16 DF Mo Abualnadi
17 DF Salim Obaid
18 FW Ibrahim Sabra
19 DF Saed Al-Rosan
20 MF Mohannad Abu Taha
21 MF Nizar Al-Rashdan
22 GK Abdallah Al-Fakhouri
23 DF Ihsan Haddad
24 FW Ali Azaizeh
25 MF Mohammad Al-Dawoud
26 DF Anas Badawi
""",
"Portugal": """
1 GK Diogo Costa
2 DF Nélson Semedo
3 DF Rúben Dias
4 DF Tomás Araújo
5 DF Diogo Dalot
6 MF Matheus Nunes
7 FW Cristiano Ronaldo
8 MF Bruno Fernandes
9 FW Gonçalo Ramos
10 MF Bernardo Silva
11 FW João Félix
12 GK José Sá
13 DF Renato Veiga
14 DF Gonçalo Inácio
15 MF João Neves
16 FW Francisco Trinção
17 FW Rafael Leão
18 FW Pedro Neto
19 FW Gonçalo Guedes
20 DF João Cancelo
21 MF Rúben Neves
22 GK Rui Silva
23 MF Vitinha
24 DF Samú Costa
25 DF Nuno Mendes
26 FW Francisco Conceição
""",
"DR Congo": """
1 GK Lionel Mpasi
2 DF Aaron Wan-Bissaka
3 DF Steve Kapuadi
4 DF Axel Tuanzebe
5 DF Dylan Batubinsika
6 MF Ngal'ayel Mukau
7 MF Nathanaël Mbuku
8 MF Samuel Moutoussamy
9 FW Brian Cipenga
10 MF Théo Bongonda
11 FW Gaël Kakuta
12 DF Joris Kayembe
13 FW Meschak Elia
14 MF Noah Sadiki
15 MF Aaron Tshibola
16 GK Timothy Fayulu
17 FW Cédric Bakambu
18 MF Charles Pickel
19 FW Fiston Mayele
20 FW Yoane Wissa
21 GK Matthieu Epolo
22 DF Chancel Mbemba
23 FW Simon Banza
24 DF Gédéon Kalulu
25 MF Edo Kayembe
26 DF Arthur Masuaku
""",
"Uzbekistan": """
1 GK Utkir Yusupov
2 DF Abdukodir Khusanov
3 DF Khojiakbar Alijonov
4 DF Farrukh Sayfiev
5 DF Rustam Ashurmatov
6 MF Akmal Mozgovoy
7 MF Otabek Shukurov
8 MF Jamshid Iskanderov
9 MF Odiljon Hamrobekov
10 MF Jaloliddin Masharipov
11 MF Oston Urunov
12 GK Abduvohid Nematov
13 DF Sherzod Nasrullaev
14 FW Eldor Shomurodov
15 DF Umar Eshmurodov
16 GK Botirali Ergashev
17 MF Dostonbek Khamdamov
18 DF Abdulla Abdullaev
19 MF Azizjon Ganiev
20 FW Azizbek Amonov
21 FW Igor Sergeev
22 MF Abbosbek Fayzullaev
23 MF Sherzod Esanov
24 DF Bekhruz Karimov
25 DF Avazbek Ulmasaliev
26 DF Jakhongir Urozov
""",
"Colombia": """
1 GK David Ospina
2 DF Daniel Muñoz
3 DF Jhon Lucumí
4 DF Santiago Arias
5 MF Kevin Castaño
6 MF Richard Ríos
7 FW Luis Díaz
8 MF Jorge Carrascal
9 FW Jhon Córdoba
10 MF James Rodríguez
11 MF Jhon Arias
12 GK Camilo Vargas
13 DF Yerry Mina
14 DF Gustavo Puerta
15 MF Juan Portilla
16 MF Jefferson Lerma
17 DF Johan Mojica
18 DF Willer Ditta
19 FW Cucho Hernández
20 MF Juan Fernando Quintero
21 FW Jaminton Campaz
22 DF Deiver Machado
23 DF Davinson Sánchez
24 GK Álvaro Montero
25 FW Luis Suárez
26 FW Andrés Gómez
""",
"England": """
1 GK Jordan Pickford
2 DF Ezri Konsa
3 DF Nico O'Reilly
4 MF Declan Rice
5 DF John Stones
6 DF Marc Guéhi
7 FW Bukayo Saka
8 MF Elliot Anderson
9 FW Harry Kane
10 MF Jude Bellingham
11 FW Marcus Rashford
12 DF Tino Livramento
13 GK Dean Henderson
14 MF Jordan Henderson
15 DF Dan Burn
16 MF Kobbie Mainoo
17 MF Morgan Rogers
18 FW Anthony Gordon
19 FW Ollie Watkins
20 FW Noni Madueke
21 MF Eberechi Eze
22 FW Ivan Toney
23 GK James Trafford
24 DF Reece James
25 DF Djed Spence
26 DF Jarell Quansah
""",
"Croatia": """
1 GK Dominik Livaković
2 DF Josip Stanišić
3 DF Marin Pongračić
4 DF Joško Gvardiol
5 DF Duje Ćaleta-Car
6 DF Josip Šutalo
7 MF Nikola Moro
8 MF Mateo Kovačić
9 FW Andrej Kramarić
10 MF Luka Modrić
11 FW Ante Budimir
12 GK Ivor Pandur
13 MF Nikola Vlašić
14 FW Ivan Perišić
15 MF Mario Pašalić
16 MF Martin Baturina
17 MF Petar Sučić
18 DF Kristijan Jakić
19 MF Toni Fruk
20 FW Igor Matanović
21 MF Luka Sučić
22 DF Luka Vušković
23 GK Dominik Kotarski
24 FW Marco Pašalić
25 DF Martin Erlić
26 FW Petar Musa
""",
"Ghana": """
1 GK Lawrence Ati-Zigi
2 DF Alidu Seidu
3 MF Caleb Yirenkyi
4 DF Jonas Adjetey
5 MF Thomas Partey
6 DF Abdul Mumin
7 FW Abdul Fatawu
8 MF Kwasi Sibo
9 FW Jordan Ayew
10 FW Brandon Thomas-Asante
11 MF Antoine Semenyo
12 GK Joseph Anang
13 FW Christopher Bonsu Baah
14 DF Gideon Mensah
15 MF Elisha Owusu
16 GK Benjamin Asare
17 DF Abdul Rahman Baba
18 DF Jerome Opoku
19 FW Iñaki Williams
20 MF Augustine Boakye
21 DF Kojo Peprah Oppong
22 FW Kamaldeen Sulemana
23 DF Derrick Luckassen
24 FW Ernest Nuamah
25 FW Prince Kwabena Adu
26 DF Marvin Senaya
""",
"Panama": """
1 GK Luis Mejía
2 DF César Blackman
3 DF José Córdoba
4 DF Fidel Escobar
5 DF Edgardo Fariña
6 MF Cristian Martínez
7 MF José Luis Rodríguez
8 MF Adalberto Carrasquilla
9 FW Tomás Rodríguez
10 MF Ismael Díaz
11 MF Yoel Bárcenas
12 GK César Samudio
13 DF Jiovany Ramos
14 DF Carlos Harvey
15 DF Eric Davis
16 DF Andrés Andrade
17 FW José Fajardo
18 FW Cecilio Waterman
19 MF Alberto Quintero
20 MF Aníbal Godoy
21 MF César Yanis
22 GK Orlando Mosquera
23 DF Michael Amir Murillo
24 FW Azarias Londoño
25 DF Roderick Miller
26 DF Jorge Gutiérrez
""",
}

LINE_RE = re.compile(r"^\s*(\d+)\s+(GK|DF|MF|FW)\s+(.+?)\s*$")

# Players currently unavailable (injury/suspension). They're flagged out and
# excluded from the auto-picked default XI. Edit, or manage live in the editor.
INJURED: dict[str, list[str]] = {
    "Brazil": ["Neymar"],
}


def baseline_rating(elo: int) -> float:
    return max(45.0, min(95.0, 50 + (elo - 1600) / 12))


def build() -> dict:
    squads: dict[str, dict] = {}
    missing = [t for t in teams_mod.ELO if t not in RAW]
    if missing:
        raise SystemExit(f"Missing roster data for: {missing}")

    for team, block in RAW.items():
        elo = teams_mod.ELO[team]
        rng = random.Random(hash(team) & 0xFFFFFFFF)
        base = baseline_rating(elo)
        players = []
        pid = 0
        for line in block.strip().splitlines():
            m = LINE_RE.match(line)
            if not m:
                continue
            number, pos, name = int(m.group(1)), POS_MAP[m.group(2)], m.group(3).strip()
            # Squad numbers 1-11 are traditionally first-choice -> small boost,
            # so default starting XIs look sensible before the user edits them.
            starter_bonus = 4 if number <= 11 else 0
            rating = max(40, min(99, round(base + starter_bonus + rng.uniform(-2.5, 2.5))))
            available = name not in INJURED.get(team, [])
            players.append({"id": pid, "number": number, "name": name,
                            "pos": pos, "rating": rating, "starter": False,
                            "available": available})
            pid += 1

        # Default starting XI from AVAILABLE players: best GK + 4 DEF + 3 MID + 3 FWD.
        need = {"GK": 1, "DEF": 4, "MID": 3, "FWD": 3}
        for pos, n in need.items():
            ranked = sorted((p for p in players if p["pos"] == pos and p["available"]),
                            key=lambda p: p["rating"], reverse=True)
            for p in ranked[:n]:
                p["starter"] = True

        starters = [p for p in players if p["starter"]]
        base_avg = sum(p["rating"] for p in starters) / len(starters)
        squads[team] = {"base_elo": elo, "base_avg": round(base_avg, 2),
                        "players": players}
    return squads


if __name__ == "__main__":
    data = build()
    with open("squads.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    total = sum(len(s["players"]) for s in data.values())
    print(f"Wrote squads.json: {len(data)} teams, {total} players.")
