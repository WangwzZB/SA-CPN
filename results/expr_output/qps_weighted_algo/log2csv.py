import re
import csv

# 设定文件路径
input_file_path = 'cpNode1_logfile.log'
output_file_path = 'output.csv'

# 特定文字
specific_text = 'Request /primes?limit=800 succeeded'

# 读取文本文件
with open(input_file_path, 'r', encoding='utf-8') as file:
    lines = file.readlines()

# 初始化CSV文件写入器
with open(output_file_path, 'w', newline='', encoding='utf-8') as csvfile:
    writer = csv.writer(csvfile)

    # 遍历每一行
    for line in lines:
        if specific_text in line:
            matches = re.findall(r'(\d+\.\d+)ms', line)
            # 如果找到匹配项，将它们作为一行写入CSV
            if matches:
                writer.writerow(matches)

print('处理完成，结果已保存到', output_file_path)