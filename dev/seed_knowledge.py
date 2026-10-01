KP = env['tutoring.knowledge.point']
names = ['有理数及其运算', '整式的加减', '一元一次方程', '几何图形初步', '数据的收集与整理']
for name in names:
    if not KP.search([('name', '=', name), ('grade', '=', '07')], limit=1):
        KP.create({'name': name, 'grade': '07'})
        print('created', name)

biaodi = env['tutoring.student'].browse(2)
SP = env['tutoring.student.point']
mastered = {'有理数及其运算': 'mastered', '整式的加减': 'basic', '一元一次方程': 'learning'}
for name, mastery in mastered.items():
    point = KP.search([('name', '=', name), ('grade', '=', '07')], limit=1)
    if point and not SP.search([('student_id', '=', biaodi.id), ('point_id', '=', point.id)], limit=1):
        SP.create({'student_id': biaodi.id, 'point_id': point.id, 'mastery': mastery})
        print('assigned', name, mastery)
env.cr.commit()
print('SEED_DONE')
