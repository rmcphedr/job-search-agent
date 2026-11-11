
Aug 4th

- Build deterministic job scraper from common ATS sites and other sources for job seeking. 
- Have Hermes run an evaluation of 10 jobs that come in
- These ranked jobs show up in my dashboard
    - dashboard should show all jobs, as well as ranked jobs. 
- Build out a new feature that allows me to make a decision on a job, which moves it to tracked jobs. This is where I can track my application status for each of the jobs. 

- The next step can take this job, condense it into markdown and transfer it off to the auto applying tool



Future:
- have a button where I can auto-applying from my tracked jobs. It can bring up the application portal, show me my tailored resume (maybe have some kind of dif doc to show how the template resume changed), and auto-fills fields with my information. this can be done by the hermes agent. 

- job evaluations will show the matching criteria that I have and a breakdown of the scoring with a reason. this is very similar to the legal recruiter app

Notes:

- I have focused a lot on the company discovery functionality, but this relies too heavily on the agent, and it a lengthy process because the agent does both disocvery and company evaluation, and then has to return jobs from the company. Here, job discovery is deterministic and evaluation happens once. It is much easier to return jobs directly, which are by far the most important to evaluate. 



August 5th:

- I want to focus first today on the functionality of the dashboard and the app to scrape jobs. I want it to be like the legal recruiting app where I can track certain jobs and it takes me through the full lifecycle of application. I can generate a resume there, save it, all connected to my hermes agent
- set up resume agent with pnuemosynth and ask it to grill me about my preferences etc. 
- Pick a job that I'm interested in, get GPT to revise it for me, use work-mode to draft a resume. I want to compare one and two-page versions. Look for feedback on current resume first. You can ask to revise one part at a time, then output the whole. sk it to reverse engineer it's process, to make as a new hermes skill and feed the hermes agent relevant context about myself. This will be a context transfer step that is essential to the working of the hermes agent. Otherwise, maybe I can find a way to automate this in chatGPT. It could be streamlined pretty efficiently. 
- give discovery agent access to my jobs inbox? perform ranking of these?

- in the dashboard I can have applications. these will be found in the tracking section. need to link to resume generator, share a common db and give cross functionality. not sure how to set this up or maybe need to merge... 
    - dd


August 6th:

- make UI design like AI apply: have a review inbox with job summary card, fit match, and then swipe to track, put as maybe, or no. Should be a minimalist interface with nice buttons and appeal. Less is more. make aesthetically appealing 




