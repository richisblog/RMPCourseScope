import sqlite3
d=sqlite3.connect('outputs/uc_davis_rmp_normalized.sqlite')
for table in ['professors','reviews','courses','professor_courses','review_course_links']:
    print(table, d.execute('select count(*) from '+table).fetchone()[0])
print('pre2013', d.execute("select count(*) from reviews where substr(date,1,4) < '2013'").fetchone()[0])
print('post2020_professors', d.execute("select count(distinct legacy_id) from reviews where substr(date,1,4) >= '2020'").fetchone()[0])
